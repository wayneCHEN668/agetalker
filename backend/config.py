# e:\MyDoc\APP\agetalker\backend\config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Debug: Verify API Key loading
_api_key = os.getenv('DASHSCOPE_API_KEY')
if _api_key:
    print(f"DEBUG: DASHSCOPE_API_KEY loaded (length: {len(_api_key)})")
else:
    print("DEBUG: DASHSCOPE_API_KEY NOT found in environment")

# ── General Configuration ─────────────────────────────────────────────────────
DEVICE = 'cpu'

# ── ASR Configuration (STEP 1) ────────────────────────────────────────────────
ASR_MODEL = 'paraformer-zh'
ASR_VAD_MODEL = 'fsmn-vad'
ASR_PUNC_MODEL = 'ct-punc'

ASR_SAMPLE_RATE = 16000
ASR_FRAME_SAMPLES = 2048        # ~128ms @ 16kHz (Preserved from original)

ASR_SILENCE_RMS = 0.008         # Silence threshold
ASR_SILENCE_FRAMES = 12         # ~1.5s (12 * 128ms) ，老年人的句间停顿时长，可以改为10以减少等待

ASR_VAD_KWARGS = {
    'max_end_silence_time': 1500,      # ms, elderly optimized，老年人的句间停顿时长
    'speech_noise_thres': 0.75,
    'max_single_segment_time': 30000,
    'min_speech_duration': 300,
}

# ── Emotion Configuration (STEP 2) ────────────────────────────────────────────
EMOTION_MODEL = 'iic/emotion2vec_plus_large'
EMOTION_CONF_THRESHOLD = 0.45   # Drop to neutral if below this
EMOTION_MIN_DURATION_S = 0.5    # Skip if too short
EMOTION_MAX_DURATION_S = 10.0   # Cap at 10s

# Smoothing Strategy
EMOTION_HISTORY_WINDOW  = 3                   # 滑动窗口大小（轮）
EMOTION_HISTORY_WEIGHTS = [0.50, 0.30, 0.20]  # 从新到旧的权重

# Russell Circumplex Model Mapping (Valence: 0-1, Arousal: 0-1)
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
LABEL_NORMALIZE_MAP = {
    # 中文标签
    '开心': 'happy',    '高兴': 'happy',    '愉快': 'happy',
    '悲伤': 'sad',      '难过': 'sad',      '伤心': 'sad',
    '愤怒': 'angry',    '生气': 'angry',
    '恐惧': 'fearful',  '害怕': 'fearful',  '焦虑': 'fearful',
    '厌恶': 'disgusted',
    '惊讶': 'surprised',
    '中性': 'neutral',  '平静': 'neutral',
    # 英文变体
    'happy': 'happy',   'joy': 'happy',
    'sad': 'sad',       'sadness': 'sad',
    'angry': 'angry',   'anger': 'angry',
    'fearful': 'fearful','fear': 'fearful', 'anxious': 'fearful',
    'disgusted': 'disgusted', 'disgust': 'disgusted',
    'surprised': 'surprised', 'surprise': 'surprised',
    'neutral': 'neutral',
}

# ── Qwen API (STEP 3) ────────────────────────────────────────────────────────
DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY', '')
QWEN_BASE_URL     = os.getenv('DASHSCOPE_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')

# 模型选择：qwen-turbo（开发调试）/ qwen-plus（生产推荐）/ qwen-max（最高质量）
QWEN_MODEL        = os.getenv('QWEN_MODEL', 'qwen-plus')

# ── LLM Generation Parameters ────────────────────────────────────────────────
LLM_MAX_TOKENS        = 256    # 单次最大生成 token 数（约 170 个中文字）
LLM_TEMPERATURE       = 0.75   # 适度创造性，避免重复
LLM_TOP_P             = 0.90
LLM_MAX_HISTORY_TURNS = 6      # 保留最近 N 轮对话（= N*2 条消息）

# ── Crisis Detection ─────────────────────────────────────────────────────────
CRISIS_KEYWORDS = [
    '不想活', '活着没意思', '死了算了', '不想活了',
    '太累了不想撑', '不想见人了', '活够了',
    '没有活下去', '了结', '轻生',
]

# ── TTS Emotion Mapping (STEP 4) ─────────────────────────────────────────────
# Note: TTS emotions are "healing symmetries" to the user's emotion
TTS_PARAMS_MAP = {
    'sad':       {'speed': 0.85, 'pitch': -2, 'style': 'gentle'},
    'fearful':   {'speed': 0.88, 'pitch': -1, 'style': 'calm'},
    'angry':     {'speed': 0.88, 'pitch': -1, 'style': 'gentle'},
    'happy':     {'speed': 1.05, 'pitch':  1, 'style': 'cheerful'},
    'disgusted': {'speed': 0.92, 'pitch': -1, 'style': 'calm'},
    'surprised': {'speed': 1.00, 'pitch':  0, 'style': 'neutral'},
    'neutral':   {'speed': 1.00, 'pitch':  0, 'style': 'neutral'},
    '_crisis':   {'speed': 0.82, 'pitch': -2, 'style': 'gentle'},
}
