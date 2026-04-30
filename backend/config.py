# e:\MyDoc\APP\agetalker\backend\config.py

# Model Configuration
EMOTION_MODEL = 'iic/emotion2vec_plus_large'
DEVICE = 'cpu'

# Inference Thresholds
CONFIDENCE_THRESHOLD = 0.45   # Drop to neutral if below this
MIN_AUDIO_DURATION_S = 0.5    # Skip if too short
MAX_AUDIO_DURATION_S = 10.0   # Cap at 10s

# Smoothing Strategy
HISTORY_WINDOW = 3            # Sliding window size
HISTORY_WEIGHTS = [0.5, 0.3, 0.2]  # [Current, Last, Last-1]

# Russell Circumplex Model Mapping (Valence: 0-1, Arousal: 0-1)
# Derived from design doc specifications
EMOTION_COORDS = {
    'neutral':   {'valence': 0.50, 'arousal': 0.20},
    'happy':     {'valence': 0.90, 'arousal': 0.70},
    'sad':       {'valence': 0.10, 'arousal': 0.20},
    'angry':     {'valence': 0.10, 'arousal': 0.90},
    'fearful':   {'valence': 0.15, 'arousal': 0.80},
    'disgusted': {'valence': 0.15, 'arousal': 0.50},
    'surprised': {'valence': 0.60, 'arousal': 0.85},
}

# Chinese Translation for Prompt/UI
EMOTION_ZH_MAP = {
    'neutral':   '平静',
    'happy':     '快乐',
    'sad':       '悲伤',
    'angry':     '愤怒',
    'fearful':   '焦虑/恐惧',
    'disgusted': '厌恶',
    'surprised': '惊讶',
}

# Label Normalization Map
LABEL_NORM_MAP = {
    '开心': 'happy',   '高兴': 'happy',   '愉快': 'happy',
    '悲伤': 'sad',     '难过': 'sad',     '伤心': 'sad',
    '愤怒': 'angry',   '生气': 'angry',
    '恐惧': 'fearful', '害怕': 'fearful', '焦虑': 'fearful',
    '厌恶': 'disgusted',
    '惊讶': 'surprised',
    '中性': 'neutral', '平静': 'neutral',
    'happy': 'happy', 'sad': 'sad', 'angry': 'angry',
    'fearful': 'fearful', 'disgusted': 'disgusted',
    'surprised': 'surprised', 'neutral': 'neutral',
    'joy': 'happy', 'fear': 'fearful', 'anger': 'angry',
    'disgust': 'disgusted', 'surprise': 'surprised',
    'anxious': 'fearful',
}
