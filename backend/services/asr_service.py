"""
ASR 服务（双模式：云端 DashScope 流式 + 本地 FunASR 兜底）。

架构说明：
- ASRService 是统一门面，根据 ASR_BACKEND 配置（'cloud' / 'local' / 'dual'）
  内部分发到 CloudASRBackend 或 LocalASRBackend。
- CloudASRBackend：每个 WebSocket 会话对应一个 DashScope Recognition 实例，
  音频帧边收边转发给云端，云端 VAD 自动断句，通过回调流式返回结果。
- LocalASRBackend：保留原 FunASR 批量推理逻辑，作为降级兜底。
"""

import asyncio
import logging
import os
from typing import Awaitable, Callable, Optional

import numpy as np

from config import (
    ASR_BACKEND,
    ASR_CLOUD_MODEL,
    ASR_CLOUD_FORMAT,
    ASR_CLOUD_LANGUAGE_HINTS,
    ASR_CLOUD_MAX_SENTENCE_SILENCE,
    ASR_CLOUD_HEARTBEAT,
    ASR_MODEL,
    ASR_VAD_MODEL,
    ASR_PUNC_MODEL,
    DEVICE,
    ASR_VAD_KWARGS,
    DASHSCOPE_API_KEY,
)
from dashscope.audio.asr import (
    Recognition,
    RecognitionCallback,
    RecognitionResult,
)

logger = logging.getLogger(__name__)

# 结果回调签名：async def callback(text: str, is_final: bool)
ASRResultCallback = Callable[[str, bool], Awaitable[None]]


# ─── 云端 ASR 后端 ────────────────────────────────────────────────────────────


class CloudASRBackend:
    """DashScope paraformer-realtime-v2 流式 ASR 后端。

    每个 WebSocket 会话创建一个 Recognition 实例：
    create_session() → send_audio() 多次 → end_session()

    SDK 的 RecognitionCallback.on_event() 运行在 SDK 内部线程中，
    通过 asyncio.run_coroutine_threadsafe() 桥接到 FastAPI 事件循环。
    """

    def __init__(self):
        import dashscope

        # 设置 DashScope API Key（SDK 需要全局配置）
        dashscope.api_key = DASHSCOPE_API_KEY
        if not DASHSCOPE_API_KEY:
            raise ValueError("DASHSCOPE_API_KEY 未配置，请设置环境变量或 .env 文件")

        self._sessions: dict = {}

        logger.info(
            f"CloudASRBackend 初始化完成 "
            f"(model={ASR_CLOUD_MODEL}, silence={ASR_CLOUD_MAX_SENTENCE_SILENCE}ms, "
            f"heartbeat={ASR_CLOUD_HEARTBEAT})"
        )

    def create_session(
        self,
        session_id: str,
        result_callback: ASRResultCallback,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        """为指定会话创建并启动一个流式 Recognition 实例。

        Args:
            session_id: 会话唯一标识。
            result_callback: async 回调函数 (text, is_final)。
            event_loop: FastAPI 的事件循环，用于跨线程调度回调。
        """
        cb = _RecognitionCallbackAdapter(
            session_id, result_callback, event_loop,
        )
        recognition = Recognition(
            model=ASR_CLOUD_MODEL,
            format=ASR_CLOUD_FORMAT,
            sample_rate=16000,
            language_hints=ASR_CLOUD_LANGUAGE_HINTS,
            max_sentence_silence=ASR_CLOUD_MAX_SENTENCE_SILENCE,
            heartbeat=ASR_CLOUD_HEARTBEAT,
            callback=cb,
        )
        recognition.start()

        # 保存到会话映射
        self._sessions[session_id] = {
            'recognition': recognition,
            'callback_adapter': cb,
        }
        logger.info(f"Cloud ASR 会话已创建: {session_id}")

    def send_audio(self, session_id: str, pcm_bytes: bytes) -> None:
        """向云端发送一帧 Int16 PCM 音频（建议每帧 ~100ms，1-16KB）。"""
        session = self._sessions.get(session_id)
        if session:
            try:
                # 记录发送的音频帧大小和类型
                logger.debug(f"Sending {len(pcm_bytes)} bytes (type={type(pcm_bytes).__name__}) to Cloud ASR")
                session['recognition'].send_audio_frame(pcm_bytes)
            except Exception as e:
                logger.error(f"Cloud ASR send_audio_frame 异常 ({session_id}): {e}", exc_info=True)

    def end_session(self, session_id: str) -> None:
        """停止并关闭指定会话的 Recognition 实例。

        注意：Recognition.stop() 是阻塞调用，应在 asyncio.to_thread() 中执行。
        """
        session = self._sessions.pop(session_id, None)
        if session:
            try:
                session['recognition'].stop()
            except Exception as e:
                logger.error(f"Cloud ASR stop 异常 ({session_id}): {e}")
            logger.info(f"Cloud ASR 会话已关闭: {session_id}")

    # ─── 内部状态 ────────────────────────────────────────────────────────────

    @property
    def sessions(self) -> dict:
        return self._sessions


class _RecognitionCallbackAdapter(RecognitionCallback):
    """桥接 DashScope SDK 回调线程 → asyncio 事件循环。

    SDK 的 on_event / on_complete / on_error 运行在 SDK 内部线程中，
    不能直接 await 异步函数。本适配器在回调中提取数据，然后通过
    run_coroutine_threadsafe 投递到 FastAPI 事件循环。

    直接继承 RecognitionCallback（而非运行时动态修改 __class__），
    确保 Python MRO 正确解析到本类的 override 而非基类的空操作。
    """

    def __init__(
        self,
        session_id: str,
        async_callback: ASRResultCallback,
        event_loop: asyncio.AbstractEventLoop,
    ):
        super().__init__()
        self._session_id = session_id
        self._async_callback = async_callback
        self._loop = event_loop

    def on_open(self) -> None:
        logger.debug(f"Cloud ASR 连接已打开: {self._session_id}")

    def on_event(self, result) -> None:
        """SDK 线程中调用：提取句子数据，投递到 asyncio 事件循环。"""
        sentence = result.get_sentence()
        if sentence and 'text' in sentence:
            text = sentence['text']
            is_final = RecognitionResult.is_sentence_end(sentence)
            asyncio.run_coroutine_threadsafe(
                self._async_callback(text, is_final),
                self._loop,
            )

    def on_complete(self) -> None:
        logger.debug(f"Cloud ASR 识别完成: {self._session_id}")

    def on_error(self, result) -> None:
        msg = getattr(result, 'message', str(result))
        logger.error(f"Cloud ASR 错误 ({self._session_id}): {msg}")

    def on_close(self) -> None:
        logger.debug(f"Cloud ASR 连接已关闭: {self._session_id}")


# ─── 本地 ASR 后端 ────────────────────────────────────────────────────────────


class LocalASRBackend:
    """FunASR paraformer-zh 本地推理后端（降级兜底）。

    保留原 ASRService 的批量推理逻辑：
    transcribe(audio: np.ndarray) → str
    """

    def __init__(self, hotwords_path: str = 'hotwords.txt'):
        from funasr import AutoModel

        logger.info(
            f"LocalASRBackend 加载中 ({ASR_MODEL}, {ASR_VAD_MODEL}, {ASR_PUNC_MODEL})..."
        )
        self.model = AutoModel(
            model=ASR_MODEL,
            vad_model=ASR_VAD_MODEL,
            punc_model=ASR_PUNC_MODEL,
            device=DEVICE,
            disable_update=True,
            vad_kwargs=ASR_VAD_KWARGS,
        )

        self.hotwords = ""
        if os.path.exists(hotwords_path):
            with open(hotwords_path, 'r', encoding='utf-8') as f:
                self.hotwords = f.read().strip().replace('\n', ' ')
            logger.info(f"Loaded hotwords: {self.hotwords[:50]}...")
        else:
            logger.warning(f"Hotwords file not found at {hotwords_path}")
        logger.info("LocalASRBackend 加载完成")

    def transcribe(self, audio: np.ndarray) -> str:
        """批量转录一段完整音频。"""
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        if len(audio) == 0:
            return ""
        try:
            res = self.model.generate(
                input=audio,
                language='zh',
                use_itn=True,
                batch_size_s=60,
                hotword=self.hotwords,
            )
            if not res or not res[0].get('text'):
                return ""
            text = res[0]['text']
            return rich_transcription_postprocess(text)
        except Exception as e:
            logger.error(f"Local ASR 推理异常: {e}")
            return ""


# ─── 统一 ASR 服务门面 ────────────────────────────────────────────────────────


class ASRService:
    """统一 ASR 服务门面，支持云端优先 + 本地兜底。

    初始化时根据 ASR_BACKEND 配置创建对应后端：
    - 'cloud': 仅云端，不加载本地模型（节省内存和启动时间）
    - 'local': 仅本地 FunASR
    - 'dual' (默认): 两者都加载，云端优先，失败自动降级

    使用方式（由 ws_asr.py 路由调用）：
        asr_service.create_session(session_id, callback, loop)
        asr_service.send_audio(session_id, pcm_bytes)   # 每帧音频
        asr_service.end_session(session_id)              # 会话结束

    本地兜底模式（active_backend == 'local'）时，由路由层自行做
    RMS 静音检测 + 攒整句，然后调用 asr_service.transcribe(audio)。
    """

    def __init__(self):
        self.cloud: Optional[CloudASRBackend] = None
        self.local: Optional[LocalASRBackend] = None
        self._active_sessions: dict[str, str] = {}  # session_id → 'cloud' | 'local'

        if ASR_BACKEND in ('cloud', 'dual'):
            try:
                self.cloud = CloudASRBackend()
                logger.info("Cloud ASR 后端已就绪")
            except Exception as e:
                logger.warning(f"Cloud ASR 后端初始化失败: {e}")
                if ASR_BACKEND == 'cloud':
                    raise  # 仅云端模式下初始化失败是致命的

        if ASR_BACKEND in ('local', 'dual'):
            try:
                self.local = LocalASRBackend()
                logger.info("Local ASR 后端已就绪")
            except Exception as e:
                logger.warning(f"Local ASR 后端初始化失败: {e}")

        if not self.cloud and not self.local:
            raise RuntimeError(
                f"ASR 后端初始化失败：cloud 和 local 均不可用 (ASR_BACKEND={ASR_BACKEND})"
            )

        logger.info(
            f"ASR 服务初始化完成 (模式={ASR_BACKEND}, "
            f"cloud={'可用' if self.cloud else '不可用'}, "
            f"local={'可用' if self.local else '不可用'})"
        )

    # ─── 会话级流式接口 ──────────────────────────────────────────────────────

    def create_session(
        self,
        session_id: str,
        result_callback: ASRResultCallback,
        event_loop: asyncio.AbstractEventLoop,
    ) -> str:
        """创建 ASR 会话。返回实际使用的后端名称 ('cloud' | 'local')。

        云端优先尝试，失败时自动降级到本地。
        """
        if self.cloud:
            try:
                self.cloud.create_session(session_id, result_callback, event_loop)
                self._active_sessions[session_id] = 'cloud'
                logger.info(f"会话 {session_id} 使用云端 ASR")
                return 'cloud'
            except Exception as e:
                logger.warning(f"Cloud ASR 会话创建失败 ({session_id}): {e}，降级到本地")

        self._active_sessions[session_id] = 'local'
        logger.info(f"会话 {session_id} 使用本地 ASR（降级模式）")
        return 'local'

    def send_audio(self, session_id: str, pcm_bytes: bytes) -> None:
        """向云端 ASR 发送一帧音频。仅在 active_backend == 'cloud' 时有效。"""
        if self._active_sessions.get(session_id) == 'cloud' and self.cloud:
            self.cloud.send_audio(session_id, pcm_bytes)

    def end_session(self, session_id: str) -> None:
        """结束 ASR 会话，释放资源。"""
        backend = self._active_sessions.pop(session_id, None)
        if backend == 'cloud' and self.cloud:
            self.cloud.end_session(session_id)

    # ─── 本地模式批量接口（兜底路径使用）────────────────────────────────────

    def transcribe(self, audio: np.ndarray) -> str:
        """本地批量转录（仅当 active_backend == 'local' 时由路由层调用）。"""
        if self.local:
            return self.local.transcribe(audio)
        return ""

    # ─── 生命周期辅助 ────────────────────────────────────────────────────────

    def needs_warmup(self) -> bool:
        """是否需要模型预热（仅本地后端需要）。"""
        return self.local is not None

    def warmup(self, dummy_audio: np.ndarray) -> None:
        """预热本地模型（消除首次推理的冷启动延迟）。"""
        if self.local:
            self.local.transcribe(dummy_audio)
            logger.info("Local ASR 模型预热完成")

    # ─── 工具方法（保持向后兼容）─────────────────────────────────────────────

    @staticmethod
    def bytes_to_float32(data: bytes) -> np.ndarray:
        """将 Int16 PCM 字节转换为 Float32 归一化数组。"""
        int16 = np.frombuffer(data, dtype=np.int16)
        return int16.astype(np.float32) / 32768.0

    @staticmethod
    def compute_rms(audio: np.ndarray) -> float:
        """计算音频数组的 RMS（用于本地模式的静音检测）。"""
        if len(audio) == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio ** 2)))

    @property
    def is_cloud_active(self) -> bool:
        """当前是否有云端后端可用（初始化时）。"""
        return self.cloud is not None
