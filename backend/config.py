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

# ── Cloud ASR Configuration (DashScope paraformer-realtime-v2) ────────────────
# ASR_BACKEND: 'cloud' = 仅云端 | 'local' = 仅本地 FunASR | 'dual' = 云端优先+本地兜底
ASR_BACKEND = os.getenv('ASR_BACKEND', 'dual')
ASR_CLOUD_MODEL = 'paraformer-realtime-v2'
ASR_CLOUD_FORMAT = 'pcm'
ASR_CLOUD_LANGUAGE_HINTS = ['zh']
# VAD 断句静音阈值（ms），老年人停顿较长，SDK 默认 800ms 偏短，设为 1200ms
ASR_CLOUD_MAX_SENTENCE_SILENCE = int(os.getenv('ASR_CLOUD_MAX_SENTENCE_SILENCE', '1200'))
ASR_CLOUD_HEARTBEAT = True   # 静音时持续发送心跳保持连接不断开

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

# ── Qwen API (STEP 3，主生成模型) ─────────────────────────────────────────────
DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY', '')
QWEN_BASE_URL     = os.getenv('DASHSCOPE_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')

# 模型选择：qwen-turbo（开发调试）/ qwen-plus（生产推荐）/ qwen-max（最高质量）
QWEN_MODEL        = os.getenv('QWEN_MODEL', 'qwen-plus')

# ── DeepSeek API（轻量路由 / 心理类别分类专用，OpenAI 兼容接口）────────────────
# 路由调用（判断心理类别）追求低延迟和低成本而非创造性，用专门的小/快模型替代 Qwen，
# 通过独立的客户端（见 llm_service.LLMService.router_client）与主生成调用完全分离，
# 两者互不阻塞、互不影响——其中一个变慢或失败都不会拖累另一个。
DEEPSEEK_API_KEY  = os.getenv('DEEPSEEK_API_KEY', '')
DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')

# deepseek-chat / deepseek-reasoner 是 legacy 别名，官方文档已标注将于 2026-07-24 停用
# （当前指向 deepseek-v4-flash 的非思考模式），直接用显式模型 ID，免得临到弃用日期前
# 措手不及。deepseek-v4-flash 本身就是官方推荐用于路由/分类/抽取这类高频轻量任务的模型，
# 跟我们这里的用途正好匹配。
DEEPSEEK_MODEL    = os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-pro')

if DEEPSEEK_API_KEY:
    print(f"DEBUG: DEEPSEEK_API_KEY loaded (length: {len(DEEPSEEK_API_KEY)})")
else:
    print("DEBUG: DEEPSEEK_API_KEY NOT found in environment（路由调用会在请求时报错并自动降级为 neutral，不影响服务启动）")

# ── LLM Generation Parameters（主生成调用，Qwen）──────────────────────────────
LLM_MAX_TOKENS        = 256    # 单次最大生成 token 数（约 170 个中文字）
LLM_TEMPERATURE       = 0.75   # 适度创造性，避免重复
LLM_TOP_P             = 0.90
LLM_MAX_HISTORY_TURNS = 6      # 保留最近 N 轮对话（= N*2 条消息）

# ── 路由调用参数（独立于主生成调用，追求低延迟而非创造性）─────────────────────
ROUTER_TEMPERATURE   = 0.1   # 低温度：分类任务要稳定，不需要创造性
ROUTER_MAX_TOKENS    = 250    # 路由只需输出一个简短 JSON，不需要太大预算
ROUTER_CONTEXT_TURNS = 2     # 传入路由 prompt 的最近对话轮数（1 轮 = 1 条 user + 1 条 assistant）

# DeepSeek API 额外参数（通过 extra_body 传入，对非 DeepSeek 后端无影响）
# 禁用思考链以压低延迟——路由调用要的是分类结果，不需要推理过程。
ROUTER_EXTRA_BODY = {'thinking': {'type': 'disabled'}}

# ── Crisis Detection ─────────────────────────────────────────────────────────
CRISIS_KEYWORDS = [
    '不想活', '活着没意思', '死了算了', '不想活了',
    '太累了不想撑', '不想见人了', '活够了',
    '没有活下去', '了结', '轻生',
    # v2 补充（来自 ROUTER_SYSTEM_PROMPT 危机信号词）
    '没人需要我了', '交代后事',
    '自杀','跳楼','上吊','割腕','轻生','死了算了','死了就解脱','死了就没事了','死了就自由了','死了就不痛苦了','死了就不难过了'
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

# ── 心理类别 → TTS 参数（语义驱动，替代声学情绪驱动）───────────────────────────
# 路由 LLM 判定心理类别后，TTS 参数由此表决定，而非 emotion2vec 的声学标签。
CATEGORY_TTS_PARAMS_MAP = {
    'depression': {'speed': 0.82, 'pitch': -2, 'style': 'gentle'},
    'anxiety':    {'speed': 0.88, 'pitch': -1, 'style': 'calm'},
    'anger':      {'speed': 0.88, 'pitch': -1, 'style': 'gentle'},
    'loneliness': {'speed': 0.85, 'pitch': -2, 'style': 'gentle'},
    'grief':      {'speed': 0.82, 'pitch': -2, 'style': 'gentle'},
    'positive':   {'speed': 1.05, 'pitch':  1, 'style': 'cheerful'},
    'neutral':    {'speed': 1.00, 'pitch':  0, 'style': 'neutral'},
    'crisis':     {'speed': 0.82, 'pitch': -2, 'style': 'gentle'},
}

# ── CosyVoice TTS API ─────────────────────────────────────────────────────────
TTS_MODEL         = 'cosyvoice-v1'
TTS_DEFAULT_VOICE = os.getenv('TTS_DEFAULT_VOICE', 'longxiaochun')

# ── 音频格式 ──────────────────────────────────────────────────────────────────
TTS_SAMPLE_RATE = 24000   # CosyVoice 输出 24kHz
TTS_CHANNELS    = 1       # 单声道
TTS_BIT_DEPTH   = 16      # 16bit PCM

# ── 参数范围（防止越界导致 API 报错）─────────────────────────────────────────
TTS_SPEED_MIN = 0.5
TTS_SPEED_MAX = 2.0
TTS_PITCH_MIN = -12
TTS_PITCH_MAX = 12

# ── 情感风格 → CosyVoice 风格标签映射 ────────────────────────────────────────
TTS_STYLE_MAP = {
    'gentle':   'gentle',
    'calm':     'calm',
    'cheerful': 'cheerful',
    'neutral':  'neutral',
}

# ── 情绪 → 音色映射（按情绪自动选择最合适的音色）──────────────────────────────
TTS_EMOTION_VOICE_MAP = {
    'happy':     'longxiaochun',   # 统一使用温柔音色（语速/语调变化已传达情绪共鸣）
    'neutral':   'longxiaochun',
    'sad':       'longxiaochun',
    'fearful':   'longxiaochun',
    'angry':     'longxiaochun',
    'disgusted': 'longxiaochun',
    'surprised': 'longxiaochun',
    '_crisis':   'longxiaochun',
}

# ── 分句阈值 ──────────────────────────────────────────────────────────────────
TTS_MAX_SENTENCE_LEN = 50
