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

# ── 本地模型缓存 ──────────────────────────────────────────────────────────────
# MODELSCOPE_CACHE 在 .env 里是相对路径，改成绝对路径，避免"从哪个目录启动"
# 决定模型下到哪里（从仓库根目录启动会认到空目录，然后重下一遍 3.9G）。
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ['MODELSCOPE_CACHE'] = os.path.abspath(
    os.path.join(_BACKEND_DIR, os.getenv('MODELSCOPE_CACHE', './.model_cache'))
)
_MODEL_DIR = os.path.join(os.environ['MODELSCOPE_CACHE'], 'models', 'iic')


def _local_or_hub(dirname: str, model_id: str) -> str:
    """缓存目录存在就直接给 funasr 本地路径——它 os.path.exists() 命中后会跳过
    整个 ModelScope 流程，启动不联网、断网也能起。目录不存在（新服务器首次部署）
    则回落到模型 ID，照常自动下载到上面的缓存目录，下次启动即走本地。"""
    path = os.path.join(_MODEL_DIR, dirname)
    return path if os.path.isdir(path) else model_id


# ── ASR Configuration (STEP 1) ────────────────────────────────────────────────
ASR_MODEL = _local_or_hub(
    'speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch', 'paraformer-zh'
)
ASR_VAD_MODEL = _local_or_hub('speech_fsmn_vad_zh-cn-16k-common-pytorch', 'fsmn-vad')
ASR_PUNC_MODEL = _local_or_hub('punc_ct-transformer_cn-en-common-vocab471067-large', 'ct-punc')

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
# VAD 断句静音阈值（ms）。云端只负责**转写分段**，切碎一点没关系——
# 「这一轮说完了没有」由下面的合并窗口判断。切得早反而有好处：中间结果能更快
# 显示给老人看。
ASR_CLOUD_MAX_SENTENCE_SILENCE = int(os.getenv('ASR_CLOUD_MAX_SENTENCE_SILENCE', '1000'))

# ── 整句合并窗口 ─────────────────────────────────────────────────────────────
# 云端给出一个 final 之后，先不急着交给 LLM，再等这么久：期间只要老人又开口
# （收到新的中间结果），就说明刚才那只是句中停顿，把两段并起来当一句。
#
# 为什么不按尾部标点做自适应（第一版这么干过，是错的）：
#   ASR 的标点是靠**韵律停顿**插进去的，老人边想边说，思考时的停顿会被插成
#   句号。实测转写「上面写的名字。叫王翠芬。」——句号出现在一句连贯话的中间。
#   于是"以句号结尾就少等"这条规则，恰好在老人话说到一半停顿时判定他说完了，
#   反而更容易切断。标点在这里不是可靠信号，唯一可靠的信号是"他又开口了"。
#
# 所以只留一个统一窗口，宁可整体多等一点。对老年人而言，被打断的代价远大于
# 多等半秒——这个值要在真实场景里调。
ASR_MERGE_WINDOW_MS = int(os.getenv('ASR_MERGE_WINDOW_MS', '1400'))
ASR_CLOUD_HEARTBEAT = True   # 静音时持续发送心跳保持连接不断开

# ── Emotion Configuration (STEP 2) ────────────────────────────────────────────
EMOTION_MODEL = _local_or_hub('emotion2vec_plus_large', 'iic/emotion2vec_plus_large')
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
DEEPSEEK_MODEL    = os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash')

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

# 危机警惕期：命中危机后，接下来 N 轮即使没有再出现危机信号，也维持警惕态
# （设计文档 §9.3「下一轮回复仍保持警惕状态」）。危机不是一轮就翻篇的事，
# 紧接着的几轮恰恰是最需要稳住的时候。
CRISIS_VIGILANCE_TURNS = 3

# ── 会话弧线与节奏 ───────────────────────────────────────────────────────────
# 一小时的陪伴对话有宏观结构：暖场 → 深入 → 收束。纯逐轮反应式的对话没有这个
# 概念，结果是把老人的哀伤话题打开之后，用一个计时器把界面抹掉就算结束了。
SESSION_OPENING_TURNS    = 3     # 前 N 轮算暖场阶段
SESSION_CLOSING_AFTER_MIN = 45   # 聊了多少分钟之后开始往收尾引导

# 连续多少轮以问句结尾就强制这一轮不再提问。
# CARE 的 E 步骤（开放提问）原本几乎每轮必做，一小时下来是 100 多个问题——
# 那是审讯不是陪伴。真正的陪伴里有沉默，也有单纯的"嗯，我懂"。
MAX_CONSECUTIVE_QUESTIONS = 3

# ── 长程记忆（事实台账 + 滚动摘要）───────────────────────────────────────────
# 对话历史只保留 6 轮（约 3~5 分钟），而一次陪伴对话可能持续一小时。没有长程
# 记忆时，第 40 分钟的模型完全不知道第 5 分钟说过什么，只能反问（老人会觉得
# "你没在听"）或者编造（违反事实红线）。
MEMORY_ENABLED = os.getenv('MEMORY_ENABLED', '1') != '0'
MEMORY_DIR     = os.getenv('MEMORY_DIR', 'data/memory')

# 台账各类条目上限：既防止文件无限增长，也保证注入 prompt 的长度可控。
# 超出时按"最近提到"淘汰最旧的。
MEMORY_MAX_PEOPLE      = 12
MEMORY_MAX_EVENTS      = 20
MEMORY_MAX_PREFERENCES = 15
MEMORY_MAX_NOTES_PER_PERSON = 6

# 滚动摘要：每滑出多少条消息触发一次压缩，以及摘要长度上限
MEMORY_SUMMARY_EVERY_N_MSGS = 8
MEMORY_SUMMARY_MAX_CHARS    = 400

# 跨会话保留多少段历史会话摘要（供"上次咱们聊到…"这类回指）
MEMORY_MAX_SESSION_SUMMARIES = 5

# ── 画像与引导采集（设计文档 2026-08-13）──────────────────────────────────────
# 画像与台账是两个东西：台账是叙事记忆（自由文本、无限增长），画像是结构化
# 状态机（有限字段、能判断"填了没有"）。后者是"不重复询问"的前提。
PROFILE_DIR = os.getenv('PROFILE_DIR', 'data/profiles')

# 一次会话最多主动起几个话头采集。一次对话可能只有 10-20 轮，问 5 条就意味着
# 25% 以上的轮次在采集，老人一定会察觉到味道变了。
# 注意：address 的首次询问不计入这个上限（它不是采集，是自我介绍的一部分）。
ELICIT_MAX_PER_SESSION = 2
# 两次主动采集之间至少隔多少轮，把上面那 2 次撑开到整段对话里
ELICIT_COOLDOWN_TURNS = 5
# 同一个字段问到第几次仍未填上就永久放弃。
# 这是整套机制里最重要的一道硬闸：没有它，"安全窗口""节流"都只是降低频率，
# 一个永远填不上的字段最终一定会被问到第五次、第十次。
ELICIT_MAX_ASK_COUNT = 2

# 观察类字段的最小样本量。样本不足时宁可留空——错误的性格判断会一直影响
# 后续所有对话的语气。
OBSERVE_MIN_TURNS         = 20   # talkativeness / interaction_preference
OBSERVE_MIN_TURNS_EMOTION = 30   # emotional_baseline
OBSERVE_MIN_SESSIONS      = 5    # attention_span

# ── 主动开口 ─────────────────────────────────────────────────────────────────
# 老人开着对话但静默多久之后，AI 先开口。远长于 ASR_SILENCE_FRAMES 的 1.5 秒
# 断句阈值——那个是"这句话说完了没有"，这个是"他是不是不想说了"。
# 量级估计，必须实机调；调错方向时宁可往长了调（被打断的代价大于多等一会儿）。
SILENCE_PROMPT_SEC = 25

# 定时招呼说完后开麦等多久算没人应答。略短于沉默唤起——没人应答时不该比
# 有人时等更久。
PROACTIVE_NO_ANSWER_SEC = 20
# 当天连续几次没人应答就停手。没有这条，设备会变成定时扰民的喇叭，
# 而且扰的是隔壁床的人。
PROACTIVE_NO_ANSWER_GIVEUP = 2
# 当天最多主动招呼几次（早中晚的量级，超过就是打扰）
PROACTIVE_MAX_PER_DAY = 3

# 夜间硬静默窗口（本地时间，含起点不含终点：21:00 <= t 或 t < 07:00 时静默）。
# 这是防配置错误的兜底：daily_routine 是 LLM 从口语里抽的，抽错一个数字就
# 可能变成半夜三点自己说话。采集来的数据不能直接驱动会发出声音的行为。
PROACTIVE_QUIET_START = 21
PROACTIVE_QUIET_END   = 7

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
