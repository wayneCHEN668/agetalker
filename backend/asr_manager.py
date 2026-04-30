import numpy as np
import logging
import os
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def bytes_to_float32(data: bytes) -> np.ndarray:
    """Int16 PCM bytes → Float32 normalized [-1.0, 1.0]."""
    int16 = np.frombuffer(data, dtype=np.int16)
    return int16.astype(np.float32) / 32768.0

def compute_rms(audio: np.ndarray) -> float:
    """Compute Root Mean Square (RMS) of audio buffer."""
    if len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio ** 2)))

class ASRManager:
    """Manages FunASR model lifecycle and inference."""
    
    def __init__(self, hotwords_path='hotwords.txt'):
        logger.info("Initializing ASR Models (Paraformer, VAD, Punc)...")
        
        # Determine device
        device = 'cpu' # Forced CPU as per design doc
        
        self.asr_model = AutoModel(
            model='paraformer-zh',
            vad_model='fsmn-vad',
            punc_model='ct-punc',
            device=device,
            disable_update=True,
            vad_kwargs={
                'max_end_silence_time': 1500, # ms, elderly optimized
                'speech_noise_thres': 0.75,
                'max_single_segment_time': 30000,
                'min_speech_duration': 300,
            }
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
            res = self.asr_model.generate(
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
            logger.error(f"Inference error: {e}")
            return ""

# Singleton instance for global use
_instance = None

def get_asr_manager():
    global _instance
    if _instance is None:
        _instance = ASRManager()
    return _instance
