import logging
from contextlib import asynccontextmanager
import numpy as np
from fastapi import FastAPI
from services.asr_service import ASRService
from services.emotion_service import EmotionService
from services.llm_service import LLMService
from services.tts_service import TTSService
import routers.ws_asr as ws_asr_router
import routers.sse_llm as sse_llm_router
import routers.stream_tts as stream_tts_router
from dotenv import load_dotenv

load_dotenv()

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for service initialization and injection."""
    logger.info("Initializing AgeTalker services...")
    
    # 1. Initialize Services
    asr_svc = ASRService()
    emotion_svc = EmotionService()
    llm_svc = LLMService()
    tts_svc = TTSService()
    
    # 2. Inject Services into Routers
    ws_asr_router.asr_service = asr_svc
    ws_asr_router.emotion_service = emotion_svc
    
    sse_llm_router.llm_service = llm_svc
    stream_tts_router.tts_service = tts_svc
    
    # 3. Warm up models (only local backends need it)
    logger.info("Warming up models...")
    if asr_svc.needs_warmup():
        dummy_audio = np.zeros(16000, dtype=np.float32)
        asr_svc.warmup(dummy_audio)
    emotion_svc.analyze(np.zeros(16000, dtype=np.float32), "warmup_session")
    
    logger.info("Services initialized and models warmed up ✅")
    yield
    # Cleanup logic (if any) could go here
    logger.info("Shutting down AgeTalker services...")

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="AgeTalker API",
    description="Unified backend for ASR, Emotion, and Companion logic",
    lifespan=lifespan
)

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(ws_asr_router.router)
app.include_router(sse_llm_router.router)
app.include_router(stream_tts_router.router)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "agetalker"}

if __name__ == "__main__":
    import uvicorn
    # Use single worker for stateful model stability as per design doc
    uvicorn.run("main:app", host="0.0.0.0", port=8050, reload=True)
