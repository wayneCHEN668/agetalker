import asyncio
import json
import base64
import logging
from datetime import datetime, timezone, timedelta
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from asr_manager import get_asr_manager, bytes_to_float32, compute_rms
from emotion_manager import get_emotion_manager
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AgeTalker ASR & Emotion Service")

# Constants from design doc
SAMPLE_RATE = 16000
FRAME_SIZE = 2048        # ~128ms @ 16kHz
SILENCE_RMS = 0.008      # Silence threshold
SILENCE_FRAMES = 12      # ~1.5s (12 * 128ms)

@app.on_event("startup")
async def startup_event():
    # Pre-load models at startup
    logger.info("Service starting up, warming up ASR and Emotion models...")
    # This might take time, but we do it once
    def warmup():
        get_asr_manager()
        get_emotion_manager()
        
    await asyncio.to_thread(warmup)
    logger.info("Models warmed up and ready ✅")

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.websocket("/ws/asr")
async def asr_endpoint(websocket: WebSocket):
    await websocket.accept()
    # Extract session_id for multi-user support
    session_id = websocket.query_params.get("session_id", "default_user")
    logger.info(f"Client connected: {websocket.client}, session_id: {session_id}")
    
    asr_manager = get_asr_manager()
    emotion_manager = get_emotion_manager()
    
    audio_buffer = []
    silent_frames = 0
    
    # Send status to client
    await websocket.send_text(json.dumps({"type": "status", "state": "listening"}))
    
    try:
        while True:
            # Receive binary PCM chunks
            data = await websocket.receive_bytes()
            chunk = bytes_to_float32(data)
            rms = compute_rms(chunk)
            
            if rms < SILENCE_RMS:
                silent_frames += 1
            else:
                silent_frames = 0
                audio_buffer.append(chunk)
            
            # If silence threshold reached and we have enough audio
            if silent_frames >= SILENCE_FRAMES and len(audio_buffer) > 5:
                audio = np.concatenate(audio_buffer)
                audio_buffer.clear()
                silent_frames = 0
                
                await websocket.send_text(json.dumps({"type": "status", "state": "processing"}))
                
                # Perform ASR and Emotion analysis concurrently
                # to reduce total latency for Step 3
                asr_task = asyncio.to_thread(asr_manager.transcribe, audio)
                emotion_task = asyncio.to_thread(emotion_manager.analyze, audio, session_id)
                
                text, emotion_res = await asyncio.gather(asr_task, emotion_task)
                
                if text.strip():
                    logger.info(f"Session {session_id} | Transcript: {text} | Emotion: {emotion_res['label_zh']} ({emotion_res['score']})")
                    
                    # Prepare base64 for history/display (Step 2)
                    audio_b64 = base64.b64encode(
                        (audio * 32768).astype(np.int16).tobytes()
                    ).decode()
                    
                    # Beijing Time (UTC+8)
                    beijing_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Combined result sent to frontend and ready for Step 3 (LLM)
                    await websocket.send_text(json.dumps({
                        "type": "transcript",
                        "text": text,
                        "emotion": emotion_res,          # Combined emotion data
                        "is_final": True,
                        "audio_b64": audio_b64,
                        "duration_ms": int(len(audio) / SAMPLE_RATE * 1000),
                        "timestamp": beijing_time
                    }))
                
                await websocket.send_text(json.dumps({"type": "status", "state": "listening"}))
                
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {websocket.client}, session_id: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}")
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "code": "PIPELINE_ERROR",
                "message": str(e)
            }))
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
