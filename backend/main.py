import asyncio
import json
import base64
import logging
from datetime import datetime, timezone, timedelta
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from asr_manager import get_asr_manager, bytes_to_float32, compute_rms
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AgeTalker ASR Service")

# Constants from design doc
SAMPLE_RATE = 16000
FRAME_SIZE = 2048        # ~128ms @ 16kHz
SILENCE_RMS = 0.008      # Silence threshold
SILENCE_FRAMES = 12      # ~1.5s (12 * 128ms)

@app.on_event("startup")
async def startup_event():
    # Pre-load models at startup
    logger.info("Service starting up, warming up ASR models...")
    # This might take time, but we do it once
    asyncio.to_thread(get_asr_manager)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.websocket("/ws/asr")
async def asr_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info(f"Client connected: {websocket.client}")
    
    asr_manager = get_asr_manager()
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
                
                # Perform transcription in a separate thread to keep WS responsive
                text = await asyncio.to_thread(asr_manager.transcribe, audio)
                
                if text.strip():
                    logger.info(f"Transcription: {text}")
                    # Prepare base64 for emotional analysis (Step 2)
                    audio_b64 = base64.b64encode(
                        (audio * 32768).astype(np.int16).tobytes()
                    ).decode()
                    
                    # Beijing Time (UTC+8)
                    beijing_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    
                    await websocket.send_text(json.dumps({
                        "type": "transcript",
                        "text": text,
                        "is_final": True,
                        "audio_b64": audio_b64,
                        "duration_ms": int(len(audio) / SAMPLE_RATE * 1000),
                        "timestamp": beijing_time
                    }))
                
                await websocket.send_text(json.dumps({"type": "status", "state": "listening"}))
                
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {websocket.client}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "code": "ASR_ERROR",
                "message": str(e)
            }))
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
