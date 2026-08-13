"""
ASR WebSocket 路由（双模式：云端流式 + 本地兜底）。

云端模式：音频帧边收边转发给 DashScope，云端 VAD 自动断句，
          流式返回中间结果（is_final:false）和最终结果（is_final:true）。
本地模式：保留 RMS 静音检测 + 攒整句 + FunASR 批量推理逻辑。

两种模式下，最终结果（is_final:true）都会触发情绪识别，并将结果一并推送给前端。
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.asr_service import ASRService
from services.emotion_service import EmotionService
from config import (
    ASR_SILENCE_RMS,
    ASR_SILENCE_FRAMES,
    ASR_SAMPLE_RATE,
    EMOTION_MAX_DURATION_S,
    ASR_MERGE_WINDOW_MS,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 情绪识别音频 buffer 的样本数上限。
# 正常情况下每次 final 结果都会清空这个 buffer；但云端异常或断连时 final 可能
# 长时间不来，buffer 就会一直涨（16kHz float32 约 64KB/s，一小时几百 MB）。
# 情绪识别本来也只用末尾 EMOTION_MAX_DURATION_S 那一段，留 1.5 倍余量足够。
_MAX_SENTENCE_SAMPLES = int(ASR_SAMPLE_RATE * EMOTION_MAX_DURATION_S * 1.5)


class SentenceAggregator:
    """
    把云端 VAD 切出来的多个 final 合并成「完整的一轮发言」。

    老人一句话中间停顿两三秒是常事，云端会切成两三段，系统于是拿着半句话
    （「我昨天去了」）就去回复了。光调大 VAD 静音阈值解决不了这个问题——
    调大之后每一轮回复都会跟着变慢。

    正确的分工是：云端 VAD 只管**转写分段**，「这一轮说完了没有」由这里判断。
    收到 final 之后先不提交，等一个短窗口；期间只要老人又开口（来了新的中间
    结果），就说明刚才只是句中停顿，取消提交、继续攒。

    窗口长度是固定的，不按尾部标点自适应——第一版那么做过，是错的：ASR 的标点
    靠**韵律停顿**插入，老人边想边说时的停顿会被插成句号。实测转写
    「上面写的名字。叫王翠芬。」，句号就出现在一句连贯话的中间。于是"以句号
    结尾就少等"这条规则，恰好在他话说到一半停顿时判定说完了，反而更容易切断。
    标点在这里不是可靠信号，唯一可靠的信号是「他又开口了」。
    """

    def __init__(self, commit):
        self._commit = commit          # async def commit(merged_text: str)
        self._parts: list[str] = []
        self._task: asyncio.Task | None = None

    @property
    def buffered(self) -> str:
        return ''.join(self._parts)

    def add_final(self, text: str) -> str:
        """收到一个 final：攒起来并重起提交计时器。返回当前已攒的完整文本。"""
        self._parts.append(text.strip())
        self._cancel_timer()
        self._task = asyncio.create_task(self._commit_after(ASR_MERGE_WINDOW_MS))
        return self.buffered

    def note_partial(self) -> bool:
        """老人又开口了：取消待提交。返回是否真的取消掉了一个。"""
        return self._cancel_timer()

    def cancel(self):
        """连接结束等场景：丢弃一切，别留下悬空任务。"""
        self._cancel_timer()
        self._parts = []

    def _cancel_timer(self) -> bool:
        cancelled = False
        if self._task and not self._task.done():
            self._task.cancel()
            cancelled = True
        self._task = None
        return cancelled

    async def _commit_after(self, delay_ms: int):
        # 被 cancel 时 CancelledError 直接上抛，任务标记为已取消即可
        await asyncio.sleep(delay_ms / 1000.0)
        merged = self.buffered
        self._parts = []
        self._task = None
        if merged:
            await self._commit(merged)

# Services will be injected from main.py
asr_service: ASRService = None
emotion_service: EmotionService = None


@router.websocket("/ws/asr")
async def asr_endpoint(websocket: WebSocket):
    print(">>> ASR WebSocket handler ENTERED <<<", flush=True)
    await websocket.accept()
    print(">>> WebSocket accepted <<<", flush=True)
    session_id = websocket.query_params.get("session_id", "default_user")
    logger.info(f"ASR Client connected: {websocket.client}, session_id: {session_id}")
    print(f">>> session_id={session_id}, asr_service={asr_service} <<<", flush=True)

    loop = asyncio.get_running_loop()

    # 根据初始化时判断哪个后端可用（无需探活，避免触发 SDK 错误）
    use_cloud = asr_service.is_cloud_active
    logger.info(f"Session {session_id} backend: {'cloud' if use_cloud else 'local'}")

    try:
        if use_cloud:
            await _handle_cloud_session(websocket, session_id, loop)
        else:
            await _handle_local_session(websocket, session_id)
    finally:
        # 确保会话资源释放
        asr_service.end_session(session_id)


async def _handle_cloud_session(
    websocket: WebSocket,
    session_id: str,
    loop: asyncio.AbstractEventLoop,
):
    """云端流式模式：边收边转发，回调推送结果。"""
    print(">>> _handle_cloud_session ENTERED <<<", flush=True)

    # 用于情绪识别的音频累积 buffer
    sentence_audio: list[np.ndarray] = []
    sentence_samples = 0
    audio_lock = asyncio.Lock()

    # ── 整句合并 ─────────────────────────────────────────────────────────────
    # 云端 VAD 只负责转写分段；「这一轮说完了没有」由这里判断。老人一句话中间
    # 停顿两三秒是常事，光靠调大 VAD 阈值会把每一轮的回复都拖慢。
    def _now_str() -> str:
        return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

    async def _send(payload: dict):
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception:
            pass  # WebSocket 可能已关闭

    async def _commit_merged(merged: str):
        """一轮发言攒完了：做情绪识别，然后交给前端。"""
        nonlocal sentence_audio, sentence_samples

        async with audio_lock:
            if sentence_audio:
                audio_for_emotion = np.concatenate(sentence_audio)
                sentence_audio.clear()
                sentence_samples = 0
            else:
                audio_for_emotion = np.zeros(16000, dtype=np.float32)

        # 情绪识别在关键路径上（转录要等它算完才发给前端）。合并整句之后音频
        # 变长了，CPU 上跑 emotion2vec 的耗时也跟着涨，这里记下来好定位。
        _t_emo = time.monotonic()
        emotion_res = await asyncio.to_thread(
            emotion_service.analyze, audio_for_emotion, session_id,
        )
        logger.info(
            f"⏱ 情绪识别 {(time.monotonic()-_t_emo)*1000:.0f}ms "
            f"({len(audio_for_emotion)/ASR_SAMPLE_RATE:.1f}s 音频)"
        )
        logger.info(
            f"Session {session_id} | Transcript: {merged} "
            f"| Emotion: {emotion_res.label_zh}"
        )
        await _send({
            "type": "transcript",
            "text": merged,
            "emotion": emotion_service.to_dict(emotion_res),
            "is_final": True,
            "timestamp": _now_str(),
        })

    aggregator = SentenceAggregator(_commit_merged)

    async def on_asr_result(text: str, is_final: bool):
        """由 CloudASRBackend 桥接到 asyncio 事件循环后调用。"""
        if is_final and text.strip():
            buffered = aggregator.add_final(text)
            # 已攒的内容先按中间结果显示，老人能看到整句在长
            await _send({
                "type": "transcript",
                "text": buffered,
                "is_final": False,
                "timestamp": _now_str(),
            })

        elif not is_final:
            # 老人又开口了：刚才那个 final 只是句中停顿，取消提交继续攒
            if aggregator.note_partial():
                logger.debug(f"Session {session_id} | 检测到续说，合并前一段")
            await _send({
                "type": "transcript",
                "text": aggregator.buffered + text,
                "is_final": False,
                "timestamp": _now_str(),
            })

    await websocket.send_text(json.dumps({"type": "status", "state": "listening"}))
    logger.info(f"Cloud ASR: Sent 'listening' status, waiting for audio frames...")

    # 延迟创建会话：收到第一帧音频后才调用 create_session() + start()
    session_created = False

    async def on_asr_disconnect():
        """云端连接非正常断开：释放旧会话，下一帧音频到达时自动重建。

        一小时的对话里云端会话超时/网络抖动几乎必然发生。以前这里只打一行日志，
        结果是系统静默失聪——老人继续说话，前端毫无反应，也不知道该重来。
        """
        nonlocal session_created
        if not session_created:
            return
        logger.warning(f"Cloud ASR 连接中断，将在下一帧音频到达时重建: {session_id}")
        asr_service.end_session(session_id)
        session_created = False
        try:
            await websocket.send_text(json.dumps({
                "type": "status",
                "state": "reconnecting",
            }))
        except Exception:
            pass

    try:
        frame_count = 0
        while True:
            data = await websocket.receive_bytes()
            frame_count += 1
            
            # 第一帧收到后立即记录
            if frame_count == 1:
                print(f">>> FIRST AUDIO FRAME: {len(data)} bytes <<<", flush=True)
                logger.info(f"✓ Received first audio frame: {len(data)} bytes")
            
            chunk = ASRService.bytes_to_float32(data)

            # 收到第一帧音频后才创建会话并 start()（避免 SDK 超时）
            if not session_created:
                print(f">>> Creating ASR session (calling start())... <<<", flush=True)
                import time
                t0 = time.monotonic()
                asr_service.create_session(
                    session_id, on_asr_result, loop, on_asr_disconnect,
                )
                elapsed = time.monotonic() - t0
                session_created = True
                print(f">>> ASR session created in {elapsed:.3f}s <<<", flush=True)
                logger.info(f"Cloud ASR session created after receiving first audio frame ({elapsed:.3f}s)")

            # 转发原始 Int16 PCM 字节给云端
            # WebSocket receive_bytes() 返回 bytes 对象，直接传给 SDK
            # DashScope SDK 期望：Int16 PCM 小端序，16kHz，单声道
            if frame_count <= 3:  # 只打印前几帧用于调试
                logger.info(f"Frame {frame_count}: {len(data)} bytes, first 8 bytes hex={data[:8].hex()}")
                print(f">>> Frame {frame_count}: {len(data)} bytes <<<", flush=True)
            asr_service.send_audio(session_id, data)
            if frame_count == 1:
                print(f">>> Frame 1 sent, looping back for more... <<<", flush=True)

            # 累积 float32 音频供情绪识别
            async with audio_lock:
                sentence_audio.append(chunk)
                sentence_samples += len(chunk)
                # 上限保护：final 迟迟不来时（云端异常/断连）丢掉最老的帧，
                # 情绪识别只需要末尾这一段
                while sentence_samples > _MAX_SENTENCE_SAMPLES and len(sentence_audio) > 1:
                    sentence_samples -= len(sentence_audio.pop(0))

    except WebSocketDisconnect as wd:
        print(f">>> WebSocketDisconnect: code={wd.code}, reason={wd.reason}, frames_received={frame_count} <<<", flush=True)
        logger.info(f"ASR Client disconnected (cloud): {session_id}, code={wd.code}, frames={frame_count}")
    except Exception as e:
        print(f">>> EXCEPTION: {type(e).__name__}: {e} <<<", flush=True)
        logger.error(
            f"WebSocket error (cloud) for session {session_id}: {e}",
            exc_info=True,
        )
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "code": "ASR_ROUTER_ERROR",
                "message": str(e),
            }))
        except Exception:
            pass
    finally:
        # 连接结束了，还挂着的合并计时器没有意义，取消掉免得留下悬空任务
        aggregator.cancel()


async def _handle_local_session(websocket: WebSocket, session_id: str):
    """本地兜底模式：RMS 静音检测 + 攒整句 + 批量推理。"""
    audio_buffer: list[np.ndarray] = []
    silent_frames = 0

    await websocket.send_text(json.dumps({"type": "status", "state": "listening"}))

    try:
        while True:
            data = await websocket.receive_bytes()
            chunk = ASRService.bytes_to_float32(data)
            rms = ASRService.compute_rms(chunk)

            if rms < ASR_SILENCE_RMS:
                silent_frames += 1
            else:
                silent_frames = 0
                audio_buffer.append(chunk)

            # 静音阈值触发推理
            if silent_frames >= ASR_SILENCE_FRAMES and len(audio_buffer) > 5:
                audio = np.concatenate(audio_buffer)
                audio_buffer.clear()
                silent_frames = 0

                await websocket.send_text(
                    json.dumps({"type": "status", "state": "processing"})
                )

                # ASR + 情绪并行
                asr_task = asyncio.to_thread(asr_service.transcribe, audio)
                emotion_task = asyncio.to_thread(
                    emotion_service.analyze, audio, session_id,
                )
                text, emotion_res = await asyncio.gather(asr_task, emotion_task)

                if text.strip():
                    logger.info(
                        f"Session {session_id} | Transcript: {text} "
                        f"| Emotion: {emotion_res.label_zh}"
                    )
                    beijing_time = datetime.now(
                        timezone(timedelta(hours=8))
                    ).strftime("%Y-%m-%d %H:%M:%S")

                    await websocket.send_text(json.dumps({
                        "type": "transcript",
                        "text": text,
                        "emotion": emotion_service.to_dict(emotion_res),
                        "is_final": True,
                        "timestamp": beijing_time,
                    }))

                await websocket.send_text(
                    json.dumps({"type": "status", "state": "listening"})
                )

    except WebSocketDisconnect:
        logger.info(f"ASR Client disconnected (local): {session_id}")
    except Exception as e:
        logger.error(
            f"WebSocket error (local) for session {session_id}: {e}",
            exc_info=True,
        )
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "code": "ASR_ROUTER_ERROR",
                "message": str(e),
            }))
        except Exception:
            pass

