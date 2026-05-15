import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from services.tts_service import TTSService
from config import TTS_SPEED_MIN, TTS_SPEED_MAX, TTS_PITCH_MIN, TTS_PITCH_MAX

logger = logging.getLogger(__name__)
router = APIRouter()

# 服务实例由 main.py 注入
tts_service: TTSService = None


# ─── Schema ──────────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text:          str   = Field(...,             description="待合成文本")
    speed:         float = Field(default=1.0,     description="语速倍率 0.5~2.0")
    pitch:         int   = Field(default=0,       description="音调偏移 -12~12（半音）")
    style:         str   = Field(default='neutral', description="情感风格")
    emotion_label: str   = Field(default='neutral', description="用户情绪标签，用于自动选音色")

    @field_validator('speed')
    @classmethod
    def validate_speed(cls, v: float) -> float:
        if not (TTS_SPEED_MIN <= v <= TTS_SPEED_MAX):
            raise ValueError(f"speed 须在 [{TTS_SPEED_MIN}, {TTS_SPEED_MAX}]")
        return v

    @field_validator('pitch')
    @classmethod
    def validate_pitch(cls, v: int) -> int:
        if not (TTS_PITCH_MIN <= v <= TTS_PITCH_MAX):
            raise ValueError(f"pitch 须在 [{TTS_PITCH_MIN}, {TTS_PITCH_MAX}]")
        return v


# ─── 路由 ────────────────────────────────────────────────────────────────────

@router.post('/tts/stream')
async def tts_stream(req: TTSRequest):
    """
    流式语音合成接口。
    返回 Content-Type: audio/pcm，格式 24kHz 16bit 单声道。
    """
    if tts_service is None:
        raise HTTPException(status_code=503, detail="TTS service not initialized")
        
    if not req.text.strip():
        raise HTTPException(status_code=400, detail='text 不能为空')

    def generate():
        try:
            for chunk in tts_service.synthesize_stream(
                text          = req.text,
                speed         = req.speed,
                pitch         = req.pitch,
                style         = req.style,
                emotion_label = req.emotion_label,
            ):
                yield chunk
        except Exception as e:
            logger.error(f"Error in tts_stream generator: {e}")
            # Generator errors in StreamingResponse are tricky, 
            # usually results in a broken connection.

    return StreamingResponse(
        generate(),
        media_type='audio/pcm',
        headers={
            'X-Sample-Rate':     str(24000),
            'X-Channels':        '1',
            'X-Bit-Depth':       '16',
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',   # 禁止 Nginx 缓冲
        },
    )


@router.get('/tts/status')
async def tts_status():
    """
    查询当前 TTS 播放状态。
    """
    if tts_service is None:
        return {'is_playing': False, 'status': 'not_initialized'}
    return {'is_playing': tts_service.is_playing}
