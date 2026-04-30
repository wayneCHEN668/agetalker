# e:\MyDoc\APP\agetalker\backend\emotion_manager.py

import numpy as np
import logging
import torch
from collections import deque
from funasr import AutoModel
from config import (
    EMOTION_MODEL, DEVICE, CONFIDENCE_THRESHOLD,
    MIN_AUDIO_DURATION_S, MAX_AUDIO_DURATION_S,
    HISTORY_WINDOW, HISTORY_WEIGHTS,
    EMOTION_COORDS, EMOTION_ZH_MAP, LABEL_NORM_MAP,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EmotionManager:
    """Manages emotion2vec model and session-based emotional history."""
    
    def __init__(self):
        logger.info(f"Loading Emotion Model: {EMOTION_MODEL} on {DEVICE}...")
        
        # Load model via FunASR
        self.model = AutoModel(
            model=EMOTION_MODEL,
            device=DEVICE,
            disable_update=True,
        )
        
        # Limit CPU threads for stability in a multi-model environment
        torch.set_num_threads(4)
        
        # Multi-user history: {session_id: deque([{'label': str, 'score': float}, ...])}
        self.session_histories = {}
        
        logger.info("Emotion Model loaded successfully ✅")

    def _get_history(self, session_id: str) -> deque:
        """Get or create sliding window for a session."""
        if session_id not in self.session_histories:
            self.session_histories[session_id] = deque(maxlen=HISTORY_WINDOW)
        return self.session_histories[session_id]

    def _normalize_label(self, raw_label: str) -> str:
        """Map model output to standard English label.
        Handles labels like '愤怒/angry' by taking the last part.
        """
        clean_label = raw_label.split('/')[-1].strip().lower()
        return LABEL_NORM_MAP.get(clean_label, 'neutral')

    def _preprocess(self, audio: np.ndarray) -> np.ndarray:
        """Normalize audio to float32 and clip to [-1, 1]."""
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        return np.clip(audio, -1.0, 1.0)

    def _smooth(self, session_id: str, current_label: str, current_score: float) -> dict:
        """Apply weighted voting using history window."""
        history = self._get_history(session_id)
        
        if not history:
            return {'label': current_label, 'score': current_score}
            
        # Tally weighted votes
        votes = {current_label: current_score * HISTORY_WEIGHTS[0]}
        
        # Add history votes (most recent first)
        for i, h in enumerate(reversed(history)):
            if (i + 1) >= len(HISTORY_WEIGHTS):
                break
            weight = HISTORY_WEIGHTS[i+1]
            label = h['label']
            votes[label] = votes.get(label, 0.0) + (h['score'] * weight)
            
        winner = max(votes, key=votes.get)
        # Cap score at 1.0
        winner_score = min(1.0, votes[winner])
        
        return {'label': winner, 'score': round(winner_score, 3)}

    def _get_trend(self, session_id: str, current_label: str) -> str:
        """Calculate emotional trend based on valence change."""
        history = self._get_history(session_id)
        if len(history) < 1:
            return "会话开始，建立情绪基准"
            
        prev_label = history[-1]['label']
        prev_v = EMOTION_COORDS.get(prev_label, {}).get('valence', 0.5)
        curr_v = EMOTION_COORDS.get(current_label, {}).get('valence', 0.5)
        
        delta = curr_v - prev_v
        prev_zh = EMOTION_ZH_MAP.get(prev_label, prev_label)
        curr_zh = EMOTION_ZH_MAP.get(current_label, current_label)
        
        if delta > 0.25:
            return f"情绪好转：从「{prev_zh}」向「{curr_zh}」转变"
        elif delta < -0.25:
            return f"情绪回落：从「{prev_zh}」向「{curr_zh}」转变"
        elif prev_label == current_label:
            return f"情绪稳定在「{curr_zh}」"
        else:
            return f"情绪平稳波动（{prev_zh} → {curr_zh}）"

    def analyze(self, audio: np.ndarray, session_id: str, sample_rate: int = 16000) -> dict:
        """Analyze audio and return smoothed emotional result."""
        # 1. Validation & Preprocessing
        audio = self._preprocess(audio)
        duration = len(audio) / sample_rate
        
        if duration < MIN_AUDIO_DURATION_S:
            logger.debug(f"Audio too short ({duration:.2f}s), skipping emotion analysis.")
            return self._get_default_result("音频过短")

        if duration > MAX_AUDIO_DURATION_S:
            # Take the last segment as it usually contains the most expressive tone
            max_samples = int(MAX_AUDIO_DURATION_S * sample_rate)
            audio = audio[-max_samples:]
            
        # 2. Inference
        try:
            # Use run_in_executor in main.py, so we can use sync generate here
            res = self.model.generate(
                input=audio,
                sample_rate=sample_rate,
                granularity='utterance',
                extract_embedding=False
            )
            
            if not res or 'scores' not in res[0] or 'labels' not in res[0]:
                return self._get_default_result("模型输出格式不完整")
                
            # Zip labels and scores to find the top1
            labels = res[0]['labels']
            scores = res[0]['scores']
            
            # Use zip to associate labels with scores
            emotion_probs = list(zip(labels, scores))
            top1_label, top1_score = max(emotion_probs, key=lambda x: x[1])
            
            raw_label = self._normalize_label(top1_label)
            raw_score = float(top1_score)
            
            # 3. Confidence Filter
            if raw_score < CONFIDENCE_THRESHOLD:
                process_label = 'neutral'
                process_score = 1.0 - raw_score # Confidence of it NOT being the other thing
            else:
                process_label = raw_label
                process_score = raw_score
                
            # 4. Smoothing & Trend
            smoothed = self._smooth(session_id, process_label, process_score)
            trend = self._get_trend(session_id, smoothed['label'])
            
            # 5. Update History
            self._get_history(session_id).append({'label': process_label, 'score': process_score})
            
            # 6. Final Pack
            coords = EMOTION_COORDS.get(smoothed['label'], EMOTION_COORDS['neutral'])
            
            return {
                'label': smoothed['label'],
                'label_zh': EMOTION_ZH_MAP.get(smoothed['label'], '未知'),
                'score': smoothed['score'],
                'valence': coords['valence'],
                'arousal': coords['arousal'],
                'trend': trend,
                'raw': {'label': raw_label, 'score': round(raw_score, 3)}
            }
            
        except Exception as e:
            logger.error(f"Emotion inference error: {e}")
            return self._get_default_result(str(e))

    def _get_default_result(self, reason: str) -> dict:
        """Return neutral fallback."""
        coords = EMOTION_COORDS['neutral']
        return {
            'label': 'neutral',
            'label_zh': '平静',
            'score': 1.0,
            'valence': coords['valence'],
            'arousal': coords['arousal'],
            'trend': "识别异常或音频不足，默认平静",
            'reason': reason
        }

# Singleton instance
_instance = None

def get_emotion_manager():
    global _instance
    if _instance is None:
        _instance = EmotionManager()
    return _instance
