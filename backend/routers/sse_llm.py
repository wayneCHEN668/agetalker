# e:\MyDoc\APP\agetalker\backend\routers\sse_llm.py

import json
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from services.llm_service import LLMService

logger = logging.getLogger(__name__)
router = APIRouter()

# 服务实例由 main.py 注入
llm_service: LLMService = None


# ─── Schema ──────────────────────────────────────────────────────────────────

class LLMRequest(BaseModel):
    text:       str  = Field(...,         description="STEP 1 转录文本")
    emotion:    dict = Field(...,         description="STEP 2 EmotionResult 序列化字典")
    session_id: str  = Field(default='default', description="会话 ID（每次对话新生成，隔离会话级状态）")
    elder_id:   str  = Field(default='default_elder', description="老人 ID（跨会话稳定，长程记忆按它归档）")


# ─── 路由 ────────────────────────────────────────────────────────────────────

@router.post('/llm/stream')
async def stream_reply(req: LLMRequest):
    """
    LLM 流式回复接口，使用 SSE（Server-Sent Events）格式。

    前端调用时机：
      收到 STEP 1 的 transcript WebSocket 消息后，立即 POST 此接口。
      req.text    = msg.text
      req.emotion = msg.emotion
    """
    if llm_service is None:
        return {"error": "LLMService not initialized"}

    async def generate():
        try:
            async for chunk in llm_service.stream_reply(
                req.text, req.emotion, req.session_id, req.elder_id,
            ):
                # SSE 格式：每条消息 "data: <json>\n\n"
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"SSE stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',   # 禁止 Nginx 缓冲，保证实时推送
        },
    )


@router.post('/llm/closing')
async def stream_closing(session_id: str = 'default', elder_id: str = 'default_elder'):
    """
    结束对话前的收束仪式：回顾今天聊到的 → 肯定 → 道别 → 约定下次。

    事件结构与 /llm/stream 一致（meta → delta... → done），前端复用同一条
    播放通路即可。应在 /llm/reset 之前调用——reset 会清掉本次的滚动摘要，
    而收尾正是靠那份摘要来做回顾的。
    """
    if llm_service is None:
        return {"error": "LLMService not initialized"}

    async def generate():
        try:
            async for chunk in llm_service.stream_closing(session_id, elder_id):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"Closing stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@router.post('/llm/proactive')
async def stream_proactive_endpoint(
    session_id: str = 'default',
    elder_id:   str = 'default_elder',
    trigger:    str = 'scheduled',
):
    """AI 主动开口（trigger: scheduled 定时招呼 / silence 沉默唤起）。

    护栏在**服务端**判断，不信任前端：夜间静默、每日上限、连续无应答、
    危机警戒期。被挡住时返回一条 blocked 事件，前端据此安静收场——
    不要重试，也不要提示老人。

    事件结构与 /llm/stream 一致（meta → delta... → done），前端复用同一条
    播放通路。
    """
    if llm_service is None:
        return {"error": "LLMService not initialized"}

    allowed, reason = llm_service.can_speak_proactively(session_id, elder_id)

    async def generate():
        if not allowed:
            logger.info(f"主动开口被护栏拦下 | session={session_id} | reason={reason}")
            payload = {'type': 'blocked', 'reason': reason}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode('utf-8')
            return
        llm_service.proactive_guard.note_spoke(elder_id)
        try:
            async for chunk in llm_service.stream_proactive(session_id, elder_id, trigger):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode('utf-8')
        except Exception as e:
            logger.error(f"Proactive stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n".encode('utf-8')

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@router.post('/llm/proactive/outcome')
async def proactive_outcome(elder_id: str = 'default_elder', answered: bool = False):
    """主动招呼之后老人到底有没有搭话。

    前端在等待窗口结束时上报。连续无应答达到阈值后，当天不再主动开口——
    没有这条，设备会变成定时扰民的喇叭。
    """
    if llm_service is None:
        return {'status': 'error', 'message': 'LLMService not initialized'}
    if answered:
        llm_service.note_proactive_answered(elder_id)
    else:
        llm_service.note_proactive_no_answer(elder_id)
    return {'status': 'ok'}


@router.post('/llm/reset')
async def reset_session(session_id: str = 'default', elder_id: str = ''):
    """
    结束/重置一次会话。

    传了 elder_id 时，会先把本次对话的滚动摘要留档进长程台账（供下次回指
    「上次咱们聊到…」），再清空会话级状态。
    """
    if llm_service:
        await llm_service.close_session(session_id, elder_id)
        llm_service.reset(session_id)
    return {'status': 'ok', 'session_id': session_id}


class TruncateRequest(BaseModel):
    session_id:  str = Field(default='default', description="会话 ID")
    spoken_text: str = Field(default='',        description="实际播放出去的回复文本")


@router.post('/llm/truncate_last')
async def truncate_last_reply(req: TruncateRequest):
    """
    老人插话打断时调用：把历史里最后一条回复截断成实际听到的部分。

    否则模型以为整段都说完了，下一轮可能引用老人根本没听到的内容。
    """
    if llm_service is None:
        return {'status': 'error', 'message': 'LLMService not initialized'}
    changed = llm_service.truncate_last_reply(req.session_id, req.spoken_text)
    return {'status': 'ok', 'truncated': changed}


@router.post('/llm/crisis/escalate')
async def escalate_to_caregiver(session_id: str = 'default'):
    """
    界面上点击「联系护理员」时调用，写一条护工升级事件。

    与自动检测出的危机事件写到同一个目录，护工端只需轮询一处。
    """
    if llm_service is None:
        return {'status': 'error', 'message': 'LLMService not initialized'}
    event = llm_service.dispatch_escalation(session_id)
    return {'status': 'ok', 'event': event}


@router.get('/llm/history')
async def get_history(session_id: str = 'default'):
    """获取指定会话的对话历史（调试用）。"""
    if llm_service is None:
        return {"error": "LLMService not initialized"}
    return {
        'session_id': session_id,
        'turns':    llm_service.get_history_turns(session_id),
        'messages': llm_service.sessions.get(session_id, []),
    }
