import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.asr_service import ASRService
from services.emotion_service import EmotionService
from config import ASR_SILENCE_RMS, ASR_SILENCE_FRAMES

logger = logging.getLogger(__name__)
router = APIRouter()

# Services will be injected from main.py
asr_service: ASRService = None
emotion_service: EmotionService = None

@router.websocket("/ws/asr")
async def asr_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = websocket.query_params.get("session_id", "default_user")
    logger.info(f"ASR Client connected: {websocket.client}, session_id: {session_id}")
    
    audio_buffer = []
    silent_frames = 0
    
    # Send initial status
    await websocket.send_text(json.dumps({"type": "status", "state": "listening"}))
    
    try:
        while True:
            # Receive binary PCM chunks (Int16)
            data = await websocket.receive_bytes()
            chunk = ASRService.bytes_to_float32(data)
            rms = ASRService.compute_rms(chunk)
            
            if rms < ASR_SILENCE_RMS:
                silent_frames += 1
            else:
                silent_frames = 0
                audio_buffer.append(chunk)
            
            # Trigger inference if silence threshold reached
            if silent_frames >= ASR_SILENCE_FRAMES and len(audio_buffer) > 5:
                audio = np.concatenate(audio_buffer)
                audio_buffer.clear()
                silent_frames = 0
                
                await websocket.send_text(json.dumps({"type": "status", "state": "processing"}))
                
                # Run ASR and Emotion analysis in parallel
                asr_task = asyncio.to_thread(asr_service.transcribe, audio)
                emotion_task = asyncio.to_thread(emotion_service.analyze, audio, session_id)
                
                text, emotion_res = await asyncio.gather(asr_task, emotion_task)
                
                if text.strip():
                    logger.info(f"Session {session_id} | Transcript: {text} | Emotion: {emotion_res.label_zh}")
                    
                    # Localized timestamp (Beijing Time UTC+8)
                    beijing_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Protocol: Unified result without audio_b64 as per Merged Design
                    await websocket.send_text(json.dumps({
                        "type": "transcript",
                        "text": text,
                        "emotion": emotion_service.to_dict(emotion_res),
                        "is_final": True,
                        "timestamp": beijing_time
                    }))
                
                await websocket.send_text(json.dumps({"type": "status", "state": "listening"}))
                
    except WebSocketDisconnect:
        logger.info(f"ASR Client disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}", exc_info=True)
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "code": "ASR_ROUTER_ERROR",
                "message": str(e)
            }))
        except:
            pass
