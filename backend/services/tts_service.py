import re
import logging
import queue
import threading
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat, ResultCallback
from typing import Generator
from config import (
    DASHSCOPE_API_KEY,
    TTS_MODEL,
    TTS_DEFAULT_VOICE,
    TTS_SPEED_MIN,
    TTS_SPEED_MAX,
    TTS_PITCH_MIN,
    TTS_PITCH_MAX,
    TTS_STYLE_MAP,
    TTS_EMOTION_VOICE_MAP,
    TTS_MAX_SENTENCE_LEN,
)

logger = logging.getLogger(__name__)
dashscope.api_key = DASHSCOPE_API_KEY


class TTSCallback(ResultCallback):
    """
    Bridge between DashScope callbacks and a Python Queue.
    """
    def __init__(self, q: queue.Queue):
        self.q = q

    def on_open(self):
        logger.debug("TTS stream opened")

    def on_data(self, data: bytes):
        # logger.debug(f"TTS data received: {len(data)} bytes")
        self.q.put(data)

    def on_complete(self):
        logger.debug("TTS stream completed")
        self.q.put(None)  # Sentinel to stop generator

    def on_error(self, message):
        logger.error(f"TTS stream error: {message}")
        self.q.put(Exception(message))

    def on_close(self):
        logger.debug("TTS stream closed")


class TTSService:
    """
    CosyVoice TTS 语音合成服务 (STEP 4)。
    
    使用 Queue 桥接 DashScope 的 WebSocket 回调，提供流式生成器接口。
    """

    def __init__(self):
        self.is_playing: bool = False
        logger.info("TTS 服务初始化完成 ✅")

    def synthesize_stream(
        self,
        text:          str,
        speed:         float = 1.0,
        pitch:         int   = 0,
        style:         str   = 'neutral',
        emotion_label: str   = 'neutral',
    ) -> Generator[bytes, None, None]:
        """
        流式语音合成，yield 原始 PCM bytes。
        音频格式：PCM 24kHz 16bit 单声道
        """
        if not text or not text.strip():
            return

        # 1. 参数预处理
        speed = max(TTS_SPEED_MIN, min(TTS_SPEED_MAX, float(speed)))
        pitch_rate = round(2.0 ** (pitch / 12.0), 2)
        style_label = TTS_STYLE_MAP.get(style, 'neutral')
        voice = TTS_EMOTION_VOICE_MAP.get(emotion_label, TTS_DEFAULT_VOICE)

        logger.info(
            f"TTS 合成 | text='{text[:20]}...' | "
            f"speed={speed} pitch={pitch_rate} style={style_label} voice={voice}"
        )

        self.is_playing = True
        try:
            # 2. 为本次流式合成建立一个队列和回调
            q = queue.Queue()
            callback = TTSCallback(q)
            
            # 3. 初始化单次合成器会话（一个会话内合成所有句子，保证语流连贯）
            additional_params = {}
            if style_label and style_label != 'neutral':
                additional_params['emotion'] = style_label

            synthesizer = SpeechSynthesizer(
                model             = TTS_MODEL,
                voice             = voice,
                format            = AudioFormat.PCM_24000HZ_MONO_16BIT,
                speech_rate       = speed,
                pitch_rate        = pitch_rate,
                callback          = callback,
                additional_params = additional_params if additional_params else None
            )

            # 4. 启动后台线程消费队列并 yield (避免阻塞主线程发送)
            def consume():
                while True:
                    item = q.get()
                    if item is None: break
                    if isinstance(item, Exception): yield item; break
                    yield item

            sentences = self._split_sentences(text)
            
            # 我们需要在一个单独的线程或协程中处理合成，或者小心控制流
            # 这里简单起见，我们直接按顺序调用 streaming_call
            for sentence in sentences:
                if not sentence.strip(): continue
                synthesizer.streaming_call(sentence)
            
            # 所有句子发送完毕后再结束
            synthesizer.streaming_complete()

            # 5. 从队列中获取所有生成的音频块
            while True:
                item = q.get()
                if item is None:  # 完成信号
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
                    
        except Exception as e:
            logger.error(f"TTS 合成流异常: {e}", exc_info=True)
            raise
        finally:
            self.is_playing = False
            logger.debug("TTS 合成流结束")

    def synthesize_full(self, *args, **kwargs) -> bytes:
        """非流式合成，返回完整 PCM。"""
        return b''.join(list(self.synthesize_stream(*args, **kwargs)))

    def _split_sentences(self, text: str) -> list[str]:
        """
        更鲁棒的分句实现，支持多种标点。
        """
        if not text:
            return []
        
        # 使用 unicode 范围确保匹配
        # \u3002 = 。
        # \uff01 = ！
        # \uff1f = ？
        pattern = r'([^。\uff01\uff1f.!?\n]+[。\uff01\uff1f.!?\n]?)'
        matches = re.findall(pattern, text)
        
        if not matches:
            return [text]
            
        return [m.strip() for m in matches if m.strip()]
