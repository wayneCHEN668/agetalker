import numpy as np
import logging
import os
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess
from config import (
    ASR_MODEL, ASR_VAD_MODEL, ASR_PUNC_MODEL, DEVICE, ASR_VAD_KWARGS
)

logger = logging.getLogger(__name__)

class ASRService:
    """FunASR paraformer-zh transcription service."""
    
    def __init__(self, hotwords_path='hotwords.txt'):
        logger.info(f"Initializing ASR Service ({ASR_MODEL}, {ASR_VAD_MODEL}, {ASR_PUNC_MODEL})...")
        
        self.model = AutoModel(
            model=ASR_MODEL,
            vad_model=ASR_VAD_MODEL,
            punc_model=ASR_PUNC_MODEL,
            device=DEVICE,
            disable_update=True,
            vad_kwargs=ASR_VAD_KWARGS
        )
        
        self.hotwords = ""
        if os.path.exists(hotwords_path):
            with open(hotwords_path, 'r', encoding='utf-8') as f:
                self.hotwords = f.read().strip().replace('\n', ' ')
            logger.info(f"Loaded hotwords: {self.hotwords[:50]}...")
        else:
            logger.warning(f"Hotwords file not found at {hotwords_path}")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio buffer to punctuated text."""
        if len(audio) == 0:
            return ""
            
        try:
            res = self.model.generate(
                input=audio,
                language='zh',
                use_itn=True,
                batch_size_s=60,
                hotword=self.hotwords
            )
            
            if not res or not res[0].get('text'):
                return ""
                
            text = res[0]['text']
            return rich_transcription_postprocess(text)
            
        except Exception as e:
            logger.error(f"ASR Inference error: {e}")
            return ""

    @staticmethod
    def bytes_to_float32(data: bytes) -> np.ndarray:
        """Convert Int16 PCM bytes to Float32 normalized array."""
        int16 = np.frombuffer(data, dtype=np.int16)
        return int16.astype(np.float32) / 32768.0

    @staticmethod
    def compute_rms(audio: np.ndarray) -> float:
        """Compute Root Mean Square (RMS) of audio buffer."""
        if len(audio) == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio ** 2)))
