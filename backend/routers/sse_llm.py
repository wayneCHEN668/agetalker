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
    session_id: str  = Field(default='default', description="会话 ID")


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
            async for chunk in llm_service.stream_reply(req.text, req.emotion, req.session_id):
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


@router.post('/llm/reset')
async def reset_session(session_id: str = 'default'):
    """重置对话历史。"""
    if llm_service:
        llm_service.reset(session_id)
    return {'status': 'ok', 'session_id': session_id}


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
