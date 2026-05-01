import numpy as np
import logging
import torch
from collections import deque
from dataclasses import dataclass
from funasr import AutoModel
from config import (
    EMOTION_MODEL, DEVICE, EMOTION_CONF_THRESHOLD,
    EMOTION_MIN_DURATION_S, EMOTION_MAX_DURATION_S,
    EMOTION_HISTORY_WINDOW, EMOTION_HISTORY_WEIGHTS,
    EMOTION_COORDS, EMOTION_ZH_MAP, LABEL_NORMALIZE_MAP,
)

logger = logging.getLogger(__name__)


# ─── 输出数据结构 ────────────────────────────────────────────────────────────

@dataclass
class EmotionResult:
    """
    情绪分析结果。
    由 STEP 1 路由层附加在 transcript 消息中推送给前端，
    同时作为未来 STEP 3 LLM 服务的入参。
    """
    # 模型原始输出（调试用）
    raw_label:  str
    raw_score:  float

    # 平滑后最终结果（STEP 3 消费）
    label:      str     # 英文标签
    label_zh:   str     # 中文标签，直接填入 Prompt
    score:      float   # 置信度 0-1

    # Russell 情感坐标（STEP 3 定量策略依据）
    valence:    float   # 效价 0-1
    arousal:    float   # 唤醒度 0-1

    # 上下文信息（STEP 3 趋势描述）
    trend:      str     # 自然语言趋势描述
    history:    list    # 最近 N 轮原始情绪记录


# ─── 情绪服务 ────────────────────────────────────────────────────────────────

class EmotionService:
    """
    emotion2vec_plus_large 情绪识别服务。
    
    设计说明：
    - 维护每个对话的情绪历史 (session_histories)
    - analyze() 接收 numpy 数组和 session_id
    - 返回 EmotionResult 数据类
    """

    def __init__(self):
        logger.info(f"正在加载情绪模型（{EMOTION_MODEL}）在 {DEVICE}...")
        self.model = AutoModel(
            model=EMOTION_MODEL,
            device=DEVICE,
            disable_update=True,
        )
        # 限制线程数以优化 CPU 负载
        torch.set_num_threads(4)
        
        # 存储不同 session 的历史记录
        self.session_histories: dict[str, deque] = {}
        logger.info("情绪服务加载完成 ✅")

    def _get_history(self, session_id: str) -> deque:
        """获取或初始化指定 session 的历史记录。"""
        if session_id not in self.session_histories:
            self.session_histories[session_id] = deque(maxlen=EMOTION_HISTORY_WINDOW)
        return self.session_histories[session_id]

    # ── 主入口 ───────────────────────────────────────────────────────────────

    def analyze(self, audio: np.ndarray, session_id: str, sample_rate: int = 16000) -> EmotionResult:
        """
        对单句音频进行情绪分析。

        Args:
            audio:       PCM 采样数据 (Float32 或 Int16)
            session_id:  会话唯一标识
            sample_rate: 采样率，默认为 16000

        Returns:
            EmotionResult 数据类实例。
        """
        # 步骤 1：预处理
        audio    = self._preprocess(audio)
        duration = len(audio) / sample_rate

        # 步骤 2：时长过滤
        if duration < EMOTION_MIN_DURATION_S:
            logger.debug(f"音频过短 ({duration:.2f}s < {EMOTION_MIN_DURATION_S}s)，返回 neutral")
            return self._make_neutral(session_id)

        # 步骤 3：超长截取末尾
        if duration > EMOTION_MAX_DURATION_S:
            max_samples = int(EMOTION_MAX_DURATION_S * sample_rate)
            audio = audio[-max_samples:]
            logger.debug(f"音频超长，截取末尾 {EMOTION_MAX_DURATION_S}s")

        # 步骤 4：模型推理
        try:
            res = self.model.generate(
                input=audio,
                sample_rate=sample_rate,
                granularity='utterance',
                extract_embedding=False,
            )
            if not res or 'scores' not in res[0]:
                return self._make_neutral(session_id)
            
            # 解析模型结果
            labels = res[0]['labels']
            scores = res[0]['scores']
            emotion_probs = list(zip(labels, scores))
            top1_label_raw, top1_score_raw = max(emotion_probs, key=lambda x: x[1])
            
            raw_label = self._normalize_label(top1_label_raw)
            raw_score = float(top1_score_raw)
            
        except Exception as e:
            logger.error(f"情绪推理异常: {e}", exc_info=True)
            return self._make_neutral(session_id)

        # 步骤 5：置信度过滤
        if raw_score < EMOTION_CONF_THRESHOLD:
            logger.debug(f"置信度不足 ({raw_score:.3f} < {EMOTION_CONF_THRESHOLD})，降级为 neutral")
            final_label = 'neutral'
            final_score = round(1.0 - raw_score, 3)
        else:
            final_label = raw_label
            final_score = raw_score

        # 步骤 6：历史平滑
        smoothed = self._smooth(session_id, final_label, final_score)

        # 步骤 7：更新历史（记录平滑前的值以保留原始波动）
        self._get_history(session_id).append({'label': final_label, 'score': final_score})

        # 步骤 8：计算趋势与坐标
        trend  = self._compute_trend(session_id)
        coords = EMOTION_COORDS.get(smoothed['label'], EMOTION_COORDS['neutral'])

        result = EmotionResult(
            raw_label  = raw_label,
            raw_score  = round(raw_score, 3),
            label      = smoothed['label'],
            label_zh   = EMOTION_ZH_MAP.get(smoothed['label'], '未知'),
            score      = round(smoothed['score'], 3),
            valence    = coords['valence'],
            arousal    = coords['arousal'],
            trend      = trend,
            history    = list(self._get_history(session_id)),
        )

        logger.info(
            f"Session {session_id} | 情绪结果: {result.label_zh}({result.score:.2f}) "
            f"V={result.valence} A={result.arousal} | {trend}"
        )
        return result

    # ── 序列化 ───────────────────────────────────────────────────────────────

    def to_dict(self, result: EmotionResult) -> dict:
        """将 EmotionResult 序列化为字典。"""
        return {
            'label':     result.label,
            'label_zh':  result.label_zh,
            'score':     result.score,
            'raw_label': result.raw_label,
            'raw_score': result.raw_score,
            'valence':   result.valence,
            'arousal':   result.arousal,
            'trend':     result.trend,
            'history':   result.history,
        }

    # ── 内部方法 ─────────────────────────────────────────────────────────────

    def _preprocess(self, audio: np.ndarray) -> np.ndarray:
        """PCM 归一化与裁剪。"""
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        return np.clip(audio, -1.0, 1.0)

    def _normalize_label(self, raw: str) -> str:
        """标签规范化。"""
        clean_label = raw.split('/')[-1].strip().lower() if '/' in raw else raw.strip()
        return LABEL_NORMALIZE_MAP.get(clean_label, 'neutral')

    def _smooth(self, session_id: str, current_label: str, current_score: float) -> dict:
        """加权历史平滑逻辑。"""
        history = self._get_history(session_id)
        if not history:
            return {'label': current_label, 'score': current_score}

        votes: dict[str, float] = {
            current_label: EMOTION_HISTORY_WEIGHTS[0] * current_score
        }

        for i, h in enumerate(reversed(list(history))):
            if i + 1 >= len(EMOTION_HISTORY_WEIGHTS):
                break
            w = EMOTION_HISTORY_WEIGHTS[i + 1]
            label = h['label']
            votes[label] = votes.get(label, 0.0) + w * h['score']

        winner       = max(votes, key=votes.get)
        winner_score = min(1.0, votes[winner])
        return {'label': winner, 'score': round(winner_score, 3)}

    def _compute_trend(self, session_id: str) -> str:
        """计算情绪趋势描述。"""
        hist = list(self._get_history(session_id))
        if len(hist) < 2:
            return '会话开始，建立情绪基准'

        prev_label = hist[-2]['label']
        curr_label = hist[-1]['label']

        prev_v = EMOTION_COORDS.get(prev_label, {}).get('valence', 0.5)
        curr_v = EMOTION_COORDS.get(curr_label, {}).get('valence', 0.5)
        delta  = curr_v - prev_v

        prev_zh = EMOTION_ZH_MAP.get(prev_label, prev_label)
        curr_zh = EMOTION_ZH_MAP.get(curr_label, curr_label)

        if delta > 0.30:
            return f'情绪明显好转（{prev_zh} → {curr_zh}）'
        elif delta < -0.30:
            return f'情绪明显下降（{prev_zh} → {curr_zh}）'
        elif curr_label == prev_label:
            return f'情绪持续稳定在「{curr_zh}」状态'
        else:
            return f'情绪平稳波动（{prev_zh} → {curr_zh}）'

    def _make_neutral(self, session_id: str) -> EmotionResult:
        """异常或静音回退结果。"""
        coords = EMOTION_COORDS['neutral']
        history = self._get_history(session_id)
        return EmotionResult(
            raw_label  = 'neutral',
            raw_score  = 1.0,
            label      = 'neutral',
            label_zh   = '平静',
            score      = 1.0,
            valence    = coords['valence'],
            arousal    = coords['arousal'],
            trend      = self._compute_trend(session_id) if history else '会话开始，建立情绪基准',
            history    = list(history),
        )

