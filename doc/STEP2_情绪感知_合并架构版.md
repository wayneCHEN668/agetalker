# STEP 2 — 情绪感知模块
**架构：单应用合并版 · emotion2vec_plus_large · 端口 8000**

---

## 目录
1. [模块概述](#1-模块概述)
2. [心理学理论基础](#2-心理学理论基础)
3. [在单应用中的位置](#3-在单应用中的位置)
4. [目录结构](#4-目录结构)
5. [配置常量](#5-配置常量)
6. [情绪标签体系](#6-情绪标签体系)
7. [核心服务实现](#7-核心服务实现)
8. [情绪历史平滑策略](#8-情绪历史平滑策略)
9. [输出数据结构](#9-输出数据结构)
10. [TDD 验收测试](#10-tdd-验收测试)

---

## 1. 模块概述

本模块接收来自 **STEP 1 路由层**的 PCM 音频（`numpy` 数组），通过 `emotion2vec_plus_large` 模型提取声学情绪特征，输出情绪标签、置信度及 Russell 情感坐标。结果以 `EmotionResult` 数据类直接返回，**无需经过任何 HTTP 接口**，由 STEP 1 路由层附加在 `transcript` 消息中一并推送给前端。

### 与旧版（独立端口 8001）的核心区别

| 维度 | 旧版（独立端口 8001） | 新版（单应用合并） |
|------|---------------------|------------------|
| 接收音频方式 | HTTP POST，Base64 解码 | **直接接收 numpy 数组** |
| 返回结果方式 | HTTP JSON 响应 | **返回 EmotionResult 数据类** |
| 与 ASR 的关系 | 串行（ASR 完成后再调情绪） | **asyncio.gather 并发执行** |
| 对外接口 | `/emotion/analyze` HTTP 端点 | **无独立 HTTP 端点** |
| 服务初始化 | 路由文件内自行初始化 | **main.py 统一初始化后注入** |
| 启动方式 | 独立 uvicorn 进程 | **随整个应用一起启动** |

### 目标指标

| 指标 | 目标值 |
|------|--------|
| 单次推理延迟（CPU） | ≤ 500ms |
| 情绪分类准确率 | ≥ 80%（纯声学特征基线） |
| 置信度阈值 | < 0.45 时自动降级为 neutral |
| 历史平滑窗口 | 最近 3 轮加权平均 |
| 与 STEP 1 并发 | 两者共享音频数据，总耗时 ≈ max(ASR, 情绪) |

---

## 2. 心理学理论基础

### 2.1 Russell 环形情感模型

emotion2vec 的分类基于 Russell（1980）二维情感空间，本模块将其转化为两个量化维度传给 STEP 3：

```
         高唤醒 (Arousal=1.0)
              ↑
    愤怒       |       快乐
  (angry)     |     (happy)
  V=0.1,A=0.9 |   V=0.9,A=0.7
              |
负效价 ───────┼─────── 正效价
(V=0.0)       |            (V=1.0)
              |
    悲伤       |       平静
    (sad)      |    (neutral)
  V=0.1,A=0.2 |   V=0.5,A=0.2
              ↓
         低唤醒 (Arousal=0.0)
```

- **Valence（效价）**：情绪正负性，0.0 = 极负面，1.0 = 极正面
- **Arousal（唤醒度）**：激活程度，0.0 = 低唤醒，1.0 = 高唤醒

这两个数值直接填入 STEP 3 的 System Prompt，让 LLM 获得**定量情绪坐标**而非模糊文字标签。

### 2.2 为什么只用声学特征

老年人真实情绪往往体现在**语调、语速、气息**上，而非字面措辞（老人表达含蓄，字面情绪弱）。纯声学模型对此更敏感，且单模型结构维护成本低，符合本项目 CPU 无 GPU 的约束。

---

## 3. 在单应用中的位置

```
main.py（应用入口）
  │
  ├── lifespan() 统一初始化
  │       └── EmotionService()   ← 本模块服务实例
  │
  └── routers/ws_asr.py          ← STEP 1 路由（调用本模块）
          │
          │  asyncio.gather()
          ├── ASRService.transcribe(audio)     ← STEP 1
          └── EmotionService.analyze(audio)    ← STEP 2（本模块）
                    │
                    │ 返回 EmotionResult（数据类，非 HTTP 响应）
                    ▼
          ws.send_text({ type: 'transcript', emotion: {...} })
                    │
                    ▼
              前端直接使用，传给 STEP 3
```

**本模块没有自己的路由文件**。`EmotionService` 是一个纯 Python 服务类，由 STEP 1 的路由层在并发任务中直接调用，结果附加在 STEP 1 的 WebSocket 消息中对外输出。

---

## 4. 目录结构

```
emotion_companion/
├── main.py                       # EmotionService 在此初始化并注入
├── config.py                     # STEP 2 相关配置在此定义
│
├── services/
│   └── emotion_service.py        # ← STEP 2 核心实现（纯 Python 类）
│
├── routers/
│   └── ws_asr.py                 # STEP 1 路由，asyncio.gather 调用本模块
│
└── tests/
    └── test_emotion_service.py   # ← STEP 2 测试
```

---

## 5. 配置常量

以下常量定义在项目统一的 `config.py` 中，STEP 2 专属部分如下：

```python
# config.py（STEP 2 相关部分）

# ── 模型 ──────────────────────────────────────────────────────────────────────
# 可降级为 emotion2vec_plus_base（~150ms）或 emotion2vec_plus_seed（~80ms）
EMOTION_MODEL = 'iic/emotion2vec_plus_large'

# ── 推理参数 ──────────────────────────────────────────────────────────────────
EMOTION_CONF_THRESHOLD = 0.45    # 低于此置信度强制降级为 neutral
EMOTION_MIN_DURATION_S = 0.5     # 音频最短时长（秒），低于此跳过推理
EMOTION_MAX_DURATION_S = 10.0    # 超过此时长截取末尾片段（秒）

# ── 历史平滑 ──────────────────────────────────────────────────────────────────
EMOTION_HISTORY_WINDOW  = 3                   # 滑动窗口大小（轮）
EMOTION_HISTORY_WEIGHTS = [0.50, 0.30, 0.20]  # 从新到旧的权重

# ── Russell 情感坐标映射 ──────────────────────────────────────────────────────
EMOTION_COORDS = {
    'neutral':   {'valence': 0.50, 'arousal': 0.20},
    'happy':     {'valence': 0.90, 'arousal': 0.70},
    'sad':       {'valence': 0.10, 'arousal': 0.20},
    'angry':     {'valence': 0.10, 'arousal': 0.90},
    'fearful':   {'valence': 0.15, 'arousal': 0.80},
    'disgusted': {'valence': 0.15, 'arousal': 0.50},
    'surprised': {'valence': 0.60, 'arousal': 0.85},
}

# ── 中文标签映射（填入 STEP 3 System Prompt）──────────────────────────────────
EMOTION_ZH_MAP = {
    'neutral':   '平静',
    'happy':     '快乐',
    'sad':       '悲伤',
    'angry':     '愤怒',
    'fearful':   '焦虑/恐惧',
    'disgusted': '厌恶',
    'surprised': '惊讶',
}

# ── 标签规范化（将模型任意输出统一为标准英文标签）────────────────────────────
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
```

---

## 6. 情绪标签体系

### 标准情绪标签（7 类）

| 英文标签 | 中文 | Valence | Arousal | 声学特征 |
|----------|------|---------|---------|----------|
| `neutral` | 平静 | 0.50 | 0.20 | 语速平稳、音调均匀 |
| `happy` | 快乐 | 0.90 | 0.70 | 语调上扬、语速加快 |
| `sad` | 悲伤 | 0.10 | 0.20 | 语调低沉、语速缓慢、气声 |
| `angry` | 愤怒 | 0.10 | 0.90 | 音量大、语速快、音调高 |
| `fearful` | 焦虑 | 0.15 | 0.80 | 颤音、语速不稳 |
| `disgusted` | 厌恶 | 0.15 | 0.50 | 鼻音重、短促停顿 |
| `surprised` | 惊讶 | 0.60 | 0.85 | 音量突变、语调急变 |

### 模型选型对比

| 模型 | 大小 | CPU 延迟 | 准确率 | 推荐场景 |
|------|------|----------|--------|----------|
| `emotion2vec_plus_large` | ~300MB | ~400ms | 最高 | **生产推荐（默认）** |
| `emotion2vec_plus_base` | ~90MB | ~150ms | 较高 | 低配机器备选 |
| `emotion2vec_plus_seed` | ~25MB | ~80ms | 一般 | 极低延迟场景 |

> 在 `config.py` 中修改 `EMOTION_MODEL` 即可切换，无需改动服务代码。

---

## 7. 核心服务实现

### `services/emotion_service.py`

```python
import numpy as np
import logging
from collections import deque
from dataclasses import dataclass
from funasr import AutoModel
from config import (
    EMOTION_MODEL,
    EMOTION_CONF_THRESHOLD,
    EMOTION_MIN_DURATION_S,
    EMOTION_MAX_DURATION_S,
    EMOTION_HISTORY_WINDOW,
    EMOTION_HISTORY_WEIGHTS,
    EMOTION_COORDS,
    EMOTION_ZH_MAP,
    LABEL_NORMALIZE_MAP,
)

logger = logging.getLogger(__name__)


# ─── 输出数据结构 ────────────────────────────────────────────────────────────

@dataclass
class EmotionResult:
    """
    情绪分析结果。
    由 STEP 1 路由层附加在 transcript 消息中推送给前端，
    同时作为 STEP 3 LLMService.stream_reply() 的入参。
    字段设计与 STEP 3 System Prompt 模板一一对应。
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
    - 纯 Python 服务类，不包含任何路由/HTTP 逻辑
    - 在 main.py 的 lifespan() 中初始化，与 ASRService 共享同一进程
    - analyze() 直接接收 numpy 数组（来自 STEP 1 的音频缓冲区），
      与 ASRService.transcribe() 并发执行，共享同一份音频数据
    - 维护每个对话的情绪历史，session 结束时调用 reset()
    """

    def __init__(self):
        logger.info(f"正在加载情绪模型（{EMOTION_MODEL}），首次约需 20s...")
        self.model = AutoModel(
            model=EMOTION_MODEL,
            device='cpu',
            disable_update=True,
        )
        # 情绪历史队列，maxlen 自动淘汰最旧的记录
        self.history: deque = deque(maxlen=EMOTION_HISTORY_WINDOW)
        logger.info("情绪模型加载完成 ✅")


    # ── 主入口 ───────────────────────────────────────────────────────────────

    def analyze(self, audio: np.ndarray, sample_rate: int = 16000) -> EmotionResult:
        """
        对单句音频进行情绪分析。

        Args:
            audio:       Float32 归一化 PCM，或 Int16 原始 PCM。
                         与 ASRService.transcribe() 共享同一个 numpy 数组，
                         在 asyncio.gather 中并发调用，无需复制数据。
            sample_rate: 采样率，应为 16000。

        Returns:
            EmotionResult 数据类实例。
            置信度不足或音频过短时返回 neutral 默认值。
        """
        # 步骤 1：预处理
        audio    = self._preprocess(audio)
        duration = len(audio) / sample_rate

        # 步骤 2：时长过滤
        if duration < EMOTION_MIN_DURATION_S:
            logger.debug(f"音频过短 ({duration:.2f}s < {EMOTION_MIN_DURATION_S}s)，返回 neutral")
            return self._make_neutral()

        # 步骤 3：超长截取末尾（老人情绪在句末往往更清晰）
        if duration > EMOTION_MAX_DURATION_S:
            max_samples = int(EMOTION_MAX_DURATION_S * sample_rate)
            audio = audio[-max_samples:]
            logger.debug(f"音频超长，截取末尾 {EMOTION_MAX_DURATION_S}s")

        # 步骤 4：模型推理
        try:
            scores = self._run_inference(audio, sample_rate)
        except Exception as e:
            logger.error(f"情绪推理异常: {e}", exc_info=True)
            return self._make_neutral()

        if not scores:
            return self._make_neutral()

        # 步骤 5：解析 top1
        top1      = max(scores, key=lambda x: x['score'])
        raw_label = self._normalize_label(top1['label'])
        raw_score = float(top1['score'])

        logger.debug(f"情绪推理原始结果: {raw_label} ({raw_score:.3f})")

        # 步骤 6：置信度过滤
        if raw_score < EMOTION_CONF_THRESHOLD:
            logger.debug(
                f"置信度不足 ({raw_score:.3f} < {EMOTION_CONF_THRESHOLD})，降级为 neutral"
            )
            final_label = 'neutral'
            final_score = round(1.0 - raw_score, 3)
        else:
            final_label = raw_label
            final_score = raw_score

        # 步骤 7：历史平滑
        smoothed = self._smooth(final_label, final_score)

        # 步骤 8：更新历史（用平滑前的值，保留真实波动）
        self.history.append({'label': final_label, 'score': final_score})

        # 步骤 9：计算趋势描述
        trend  = self._compute_trend()
        coords = EMOTION_COORDS[smoothed['label']]

        result = EmotionResult(
            raw_label  = raw_label,
            raw_score  = round(raw_score, 3),
            label      = smoothed['label'],
            label_zh   = EMOTION_ZH_MAP[smoothed['label']],
            score      = round(smoothed['score'], 3),
            valence    = coords['valence'],
            arousal    = coords['arousal'],
            trend      = trend,
            history    = list(self.history),
        )

        logger.info(
            f"情绪结果: {result.label}({result.score:.2f}) "
            f"V={result.valence} A={result.arousal} | {trend}"
        )
        return result


    # ── 序列化（供 STEP 1 路由层附加到 WebSocket 消息）─────────────────────

    def to_dict(self, result: EmotionResult) -> dict:
        """
        将 EmotionResult 序列化为字典。
        由 ws_asr.py 调用，附加在 transcript 消息的 emotion 字段中。
        前端和 STEP 3 直接使用此字典。
        """
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


    # ── 会话管理 ─────────────────────────────────────────────────────────────

    def reset(self):
        """
        新对话开始时调用，清除情绪历史。
        由 main.py 的 /session/reset 端点统一触发。
        """
        self.history.clear()
        logger.info("情绪历史已重置")


    # ── 内部方法 ─────────────────────────────────────────────────────────────

    def _preprocess(self, audio: np.ndarray) -> np.ndarray:
        """统一转为 Float32，进行幅值裁剪防止削波。"""
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        return np.clip(audio, -1.0, 1.0)

    def _run_inference(self, audio: np.ndarray, sample_rate: int) -> list:
        """
        调用 emotion2vec 模型推理。

        Returns:
            [ {'label': str, 'score': float}, ... ]  全部类别得分列表
        """
        result = self.model.generate(
            input             = audio,
            sample_rate       = sample_rate,
            output_dir        = None,
            granularity       = 'utterance',   # 句级情绪，非帧级
            extract_embedding = False,          # 不需要嵌入向量，节省内存
        )
        if not result or 'scores' not in result[0]:
            return []
        return result[0]['scores']

    def _normalize_label(self, raw: str) -> str:
        """将模型输出的任意标签规范化为 7 类标准英文标签。"""
        normalized = LABEL_NORMALIZE_MAP.get(raw.strip())
        if normalized is None:
            logger.warning(f"未知情绪标签 '{raw}'，映射为 neutral")
            return 'neutral'
        return normalized

    def _smooth(self, current_label: str, current_score: float) -> dict:
        """
        加权历史平滑。

        对最近 N 轮情绪进行带权投票，抑制单次误判导致的情绪剧烈跳变。
        权重从新到旧递减：[0.50, 0.30, 0.20]

        Args:
            current_label: 当前轮次原始情绪标签
            current_score: 当前轮次置信度

        Returns:
            {'label': str, 'score': float}  平滑后情绪
        """
        if not self.history:
            return {'label': current_label, 'score': current_score}

        # 累计带权票数
        votes: dict[str, float] = {
            current_label: EMOTION_HISTORY_WEIGHTS[0] * current_score
        }

        # 历史记录从新到旧排列
        for i, h in enumerate(reversed(list(self.history))):
            if i + 1 >= len(EMOTION_HISTORY_WEIGHTS):
                break
            w = EMOTION_HISTORY_WEIGHTS[i + 1]
            label = h['label']
            votes[label] = votes.get(label, 0.0) + w * h['score']

        winner       = max(votes, key=votes.get)
        winner_score = min(1.0, votes[winner])
        return {'label': winner, 'score': round(winner_score, 3)}

    def _compute_trend(self) -> str:
        """
        根据情绪历史生成自然语言趋势描述。
        此字符串直接填入 STEP 3 的 System Prompt，
        让 LLM 感知情绪变化方向，而不只是当前状态。
        """
        hist = list(self.history)

        if len(hist) < 2:
            return '首次对话，情绪基线未建立'

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

    def _make_neutral(self) -> EmotionResult:
        """返回默认 neutral 结果，用于时长不足、推理异常等回退场景。"""
        coords = EMOTION_COORDS['neutral']
        return EmotionResult(
            raw_label  = 'neutral',
            raw_score  = 1.0,
            label      = 'neutral',
            label_zh   = '平静',
            score      = 1.0,
            valence    = coords['valence'],
            arousal    = coords['arousal'],
            trend      = self._compute_trend() if self.history else '首次对话，情绪基线未建立',
            history    = list(self.history),
        )
```

---

## 8. 情绪历史平滑策略

### 8.1 设计动机

老年人语音有以下特点，容易触发单帧误判：

| 现象 | 可能被误判为 |
|------|------------|
| 气声、颤音 | `fearful` |
| 激动讲故事、语速加快 | `angry` |
| 停顿过多导致音频能量不均 | `neutral` → 反复跳变 |

通过 **3 轮加权投票**有效抑制单次误判，避免情绪剧烈跳变影响 STEP 3 的回复策略。

### 8.2 平滑算法图示

```
轮次:     第1轮      第2轮      第3轮（当前）
标签:     happy      happy      angry
置信度:   0.82       0.78       0.61
权重:     0.20       0.30       0.50

─────────────────────────────────────────────
带权票数:
  happy = 0.20×0.82 + 0.30×0.78 = 0.398
  angry = 0.50×0.61             = 0.305

最终结果: happy ✅（成功抑制一次 angry 误判）
```

### 8.3 参数调整指引

| 场景 | 问题 | 调整方案 |
|------|------|----------|
| 老人情绪变化快 | 平滑导致响应滞后 | 将 `EMOTION_HISTORY_WEIGHTS[0]` 从 0.50 提高到 0.65 |
| 噪音环境较差 | 误判频繁 | 将 `EMOTION_CONF_THRESHOLD` 提高到 0.55 |
| 情绪持续低落需快速响应 | 平滑掩盖真实情绪 | 将窗口 `EMOTION_HISTORY_WINDOW` 缩小到 2 |

---

## 9. 输出数据结构

`EmotionResult` 被序列化后附加在 STEP 1 的 `transcript` 消息中，格式如下：

```json
{
  "type": "transcript",
  "text": "今天一直在想我老伴，他走了三年了。",
  "is_final": true,
  "emotion": {
    "label":     "sad",
    "label_zh":  "悲伤",
    "score":     0.718,
    "raw_label": "sad",
    "raw_score": 0.731,
    "valence":   0.10,
    "arousal":   0.20,
    "trend":     "情绪持续稳定在「悲伤」状态",
    "history": [
      { "label": "neutral", "score": 0.682 },
      { "label": "sad",     "score": 0.611 },
      { "label": "sad",     "score": 0.731 }
    ]
  },
  "timestamp": 1712345678.123
}
```

前端 `useASR.ts` 的 `onTranscript` 回调直接将 `event.emotion` 传给 STEP 3 的 `useLLM.streamReply()`，**无需再发任何额外请求**。

---

## 10. TDD 验收测试

### `tests/test_emotion_service.py`

```python
import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from collections import deque


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    """
    初始化 EmotionService，mock 掉 AutoModel。
    每个测试用例使用独立实例，确保历史状态隔离。
    """
    with patch('services.emotion_service.AutoModel') as mock_cls:
        mock_cls.return_value = MagicMock()
        from services.emotion_service import EmotionService
        service = EmotionService()
        service.model = mock_cls.return_value
    return service


def make_audio(duration_s: float = 2.0) -> np.ndarray:
    """生成 Float32 正弦波测试音频（16kHz）"""
    samples = int(16000 * duration_s)
    t = np.linspace(0, duration_s, samples)
    return (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)


def mock_scores(label: str, score: float) -> list:
    """
    构造 emotion2vec 风格的全类别 scores 输出。
    指定标签得到目标分数，其余标签均分剩余分数。
    """
    all_labels = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']
    remaining  = (1.0 - score) / (len(all_labels) - 1)
    return [
        {'label': l, 'score': score if l == label else remaining}
        for l in all_labels
    ]


# ─── TC-01: 前置校验 ──────────────────────────────────────────────────────────

class TestPrecheck:

    def test_short_audio_returns_neutral_without_inference(self, svc):
        """TC-01: 音频时长 < 0.5s 时直接返回 neutral，不调用模型"""
        short_audio = make_audio(duration_s=0.3)
        result = svc.analyze(short_audio)
        assert result.label == 'neutral'
        svc.model.generate.assert_not_called()

    def test_exactly_min_duration_triggers_inference(self, svc):
        """TC-02: 音频时长 = EMOTION_MIN_DURATION_S 时正常执行推理"""
        from config import EMOTION_MIN_DURATION_S
        svc.model.generate.return_value = [{'scores': mock_scores('neutral', 0.8)}]
        audio = make_audio(duration_s=EMOTION_MIN_DURATION_S)
        svc.analyze(audio)
        svc.model.generate.assert_called_once()

    def test_int16_audio_accepted_without_error(self, svc):
        """TC-03: Int16 类型音频被自动转换，不报错"""
        svc.model.generate.return_value = [{'scores': mock_scores('neutral', 0.8)}]
        int16_audio = (make_audio(duration_s=2.0) * 32768).astype(np.int16)
        result = svc.analyze(int16_audio)
        valid_labels = {'neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised'}
        assert result.label in valid_labels

    def test_long_audio_truncated_to_max(self, svc):
        """TC-04: 超长音频被截取，模型接收的数据不超过 max 时长"""
        from config import EMOTION_MAX_DURATION_S
        svc.model.generate.return_value = [{'scores': mock_scores('neutral', 0.8)}]
        long_audio = make_audio(duration_s=EMOTION_MAX_DURATION_S + 5)
        svc.analyze(long_audio)
        call_args   = svc.model.generate.call_args
        passed_audio = call_args.kwargs.get('input') or call_args.args[0]
        max_samples  = int(EMOTION_MAX_DURATION_S * 16000)
        assert len(passed_audio) <= max_samples


# ─── TC-02: 预处理 ────────────────────────────────────────────────────────────

class TestPreprocess:

    def test_float32_unchanged(self, svc):
        """TC-05: Float32 音频经过预处理后类型不变"""
        audio  = make_audio()
        result = svc._preprocess(audio)
        assert result.dtype == np.float32

    def test_int16_converted_to_float32(self, svc):
        """TC-06: Int16 音频被转换为 Float32"""
        audio  = (make_audio() * 32768).astype(np.int16)
        result = svc._preprocess(audio)
        assert result.dtype == np.float32

    def test_clipping_applied(self, svc):
        """TC-07: 超出 [-1, 1] 的值被裁剪"""
        audio        = np.array([2.0, -3.0, 0.5], dtype=np.float32)
        result       = svc._preprocess(audio)
        assert float(result.max()) <= 1.0
        assert float(result.min()) >= -1.0


# ─── TC-03: 置信度过滤 ────────────────────────────────────────────────────────

class TestConfidenceFilter:

    def test_low_confidence_falls_back_to_neutral(self, svc):
        """TC-08: 置信度 < EMOTION_CONF_THRESHOLD 时强制降级为 neutral"""
        from config import EMOTION_CONF_THRESHOLD
        low_score = EMOTION_CONF_THRESHOLD - 0.05
        svc.model.generate.return_value = [{'scores': mock_scores('angry', low_score)}]
        result = svc.analyze(make_audio())
        assert result.label == 'neutral'

    def test_above_threshold_keeps_label(self, svc):
        """TC-09: 置信度 >= EMOTION_CONF_THRESHOLD 时保留原始标签"""
        from config import EMOTION_CONF_THRESHOLD
        high_score = EMOTION_CONF_THRESHOLD + 0.10
        svc.model.generate.return_value = [{'scores': mock_scores('sad', high_score)}]
        result = svc.analyze(make_audio())
        # 无历史时平滑不影响结果
        assert result.label == 'sad'

    def test_exact_threshold_keeps_label(self, svc):
        """TC-10: 置信度恰好等于阈值时保留标签（边界值测试）"""
        from config import EMOTION_CONF_THRESHOLD
        svc.model.generate.return_value = [{'scores': mock_scores('happy', EMOTION_CONF_THRESHOLD)}]
        result = svc.analyze(make_audio())
        assert result.label == 'happy'


# ─── TC-04: 标签规范化 ────────────────────────────────────────────────────────

class TestLabelNormalization:

    def test_chinese_happy_normalized(self, svc):
        """TC-11: 中文标签「开心」规范化为 happy"""
        assert svc._normalize_label('开心') == 'happy'

    def test_chinese_sad_normalized(self, svc):
        """TC-12: 中文标签「难过」规范化为 sad"""
        assert svc._normalize_label('难过') == 'sad'

    def test_english_variant_normalized(self, svc):
        """TC-13: 英文变体 anger 规范化为 angry"""
        assert svc._normalize_label('anger') == 'angry'

    def test_unknown_label_maps_to_neutral(self, svc):
        """TC-14: 未知标签映射为 neutral，不报错"""
        result = svc._normalize_label('未知情绪xyz')
        assert result == 'neutral'

    def test_all_standard_labels_normalized(self, svc):
        """TC-15: 7 个标准英文标签自身规范化后不变"""
        labels = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']
        for label in labels:
            assert svc._normalize_label(label) == label


# ─── TC-05: 历史平滑 ─────────────────────────────────────────────────────────

class TestHistorySmoothing:

    def test_no_history_returns_current(self, svc):
        """TC-16: 无历史时直接返回当前结果"""
        result = svc._smooth('happy', 0.90)
        assert result['label'] == 'happy'
        assert result['score'] == 0.90

    def test_single_misclassification_suppressed(self, svc):
        """TC-17: 两轮 happy 后单次低分 angry，平滑结果仍为 happy"""
        svc.history.append({'label': 'happy', 'score': 0.85})
        svc.history.append({'label': 'happy', 'score': 0.80})
        result = svc._smooth('angry', 0.52)
        assert result['label'] == 'happy'

    def test_consistent_label_wins(self, svc):
        """TC-18: 三轮一致情绪，平滑结果保持不变"""
        svc.history.append({'label': 'sad', 'score': 0.75})
        svc.history.append({'label': 'sad', 'score': 0.78})
        result = svc._smooth('sad', 0.80)
        assert result['label'] == 'sad'

    def test_score_capped_at_one(self, svc):
        """TC-19: 平滑后分数不超过 1.0"""
        svc.history.append({'label': 'happy', 'score': 0.99})
        svc.history.append({'label': 'happy', 'score': 0.99})
        result = svc._smooth('happy', 0.99)
        assert result['score'] <= 1.0


# ─── TC-06: 趋势描述 ─────────────────────────────────────────────────────────

class TestTrend:

    def test_no_history_returns_baseline_message(self, svc):
        """TC-20: 无历史时返回首次对话提示"""
        trend = svc._compute_trend()
        assert '首次对话' in trend

    def test_emotion_improvement_detected(self, svc):
        """TC-21: 从 sad 到 happy，趋势含「好转」"""
        svc.history.append({'label': 'sad',   'score': 0.70})
        svc.history.append({'label': 'happy', 'score': 0.80})
        assert '好转' in svc._compute_trend()

    def test_emotion_decline_detected(self, svc):
        """TC-22: 从 happy 到 sad，趋势含「下降」"""
        svc.history.append({'label': 'happy', 'score': 0.80})
        svc.history.append({'label': 'sad',   'score': 0.75})
        assert '下降' in svc._compute_trend()

    def test_stable_emotion_detected(self, svc):
        """TC-23: 连续两轮相同情绪，趋势含「稳定」"""
        svc.history.append({'label': 'neutral', 'score': 0.70})
        svc.history.append({'label': 'neutral', 'score': 0.72})
        assert '稳定' in svc._compute_trend()

    def test_trend_contains_chinese_labels(self, svc):
        """TC-24: 趋势描述使用中文标签，不使用英文"""
        svc.history.append({'label': 'sad',  'score': 0.70})
        svc.history.append({'label': 'happy','score': 0.80})
        trend = svc._compute_trend()
        assert 'sad' not in trend and 'happy' not in trend
        assert '悲伤' in trend or '快乐' in trend


# ─── TC-07: 会话管理 ─────────────────────────────────────────────────────────

class TestSessionManagement:

    def test_reset_clears_history(self, svc):
        """TC-25: reset 后情绪历史为空"""
        svc.history.append({'label': 'happy', 'score': 0.8})
        svc.reset()
        assert len(svc.history) == 0

    def test_history_window_respected(self, svc):
        """TC-26: 历史窗口满后自动淘汰最旧记录"""
        from config import EMOTION_HISTORY_WINDOW
        for i in range(EMOTION_HISTORY_WINDOW + 3):
            svc.history.append({'label': 'happy', 'score': 0.8})
        assert len(svc.history) == EMOTION_HISTORY_WINDOW

    def test_history_updated_after_analyze(self, svc):
        """TC-27: analyze 后历史长度加 1"""
        svc.model.generate.return_value = [{'scores': mock_scores('happy', 0.8)}]
        before = len(svc.history)
        svc.analyze(make_audio())
        assert len(svc.history) == before + 1


# ─── TC-08: 输出格式 ─────────────────────────────────────────────────────────

class TestOutputFormat:

    def test_to_dict_has_all_required_fields(self, svc):
        """TC-28: to_dict 输出包含 STEP 3 所需全部字段"""
        svc.model.generate.return_value = [{'scores': mock_scores('happy', 0.80)}]
        result = svc.analyze(make_audio())
        d = svc.to_dict(result)
        required = ['label', 'label_zh', 'score', 'raw_label',
                    'raw_score', 'valence', 'arousal', 'trend', 'history']
        for field in required:
            assert field in d, f"缺少字段: {field}"

    def test_valence_in_valid_range(self, svc):
        """TC-29: valence 值在 [0.0, 1.0] 范围内"""
        svc.model.generate.return_value = [{'scores': mock_scores('angry', 0.75)}]
        result = svc.analyze(make_audio())
        assert 0.0 <= result.valence <= 1.0

    def test_arousal_in_valid_range(self, svc):
        """TC-30: arousal 值在 [0.0, 1.0] 范围内"""
        svc.model.generate.return_value = [{'scores': mock_scores('angry', 0.75)}]
        result = svc.analyze(make_audio())
        assert 0.0 <= result.arousal <= 1.0

    def test_label_zh_is_non_empty_chinese(self, svc):
        """TC-31: label_zh 为非空中文字符串"""
        svc.model.generate.return_value = [{'scores': mock_scores('sad', 0.80)}]
        result = svc.analyze(make_audio())
        assert result.label_zh
        assert any('\u4e00' <= c <= '\u9fff' for c in result.label_zh)

    def test_history_is_list(self, svc):
        """TC-32: history 字段为列表类型"""
        svc.model.generate.return_value = [{'scores': mock_scores('neutral', 0.8)}]
        result = svc.analyze(make_audio())
        assert isinstance(result.history, list)

    def test_all_7_emotions_have_valid_coords(self):
        """TC-33: 7 种情绪标签均有 valence 和 arousal 坐标"""
        from config import EMOTION_COORDS
        labels = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']
        for label in labels:
            assert label in EMOTION_COORDS
            coords = EMOTION_COORDS[label]
            assert 0.0 <= coords['valence'] <= 1.0
            assert 0.0 <= coords['arousal'] <= 1.0


# ─── TC-09: 异常处理 ─────────────────────────────────────────────────────────

class TestExceptionHandling:

    def test_model_exception_returns_neutral(self, svc):
        """TC-34: 模型推理抛出异常时，返回 neutral 不崩溃"""
        svc.model.generate.side_effect = RuntimeError("模型内部错误")
        result = svc.analyze(make_audio())
        assert result.label == 'neutral'

    def test_empty_scores_returns_neutral(self, svc):
        """TC-35: 模型返回空 scores 时返回 neutral"""
        svc.model.generate.return_value = [{'scores': []}]
        result = svc.analyze(make_audio())
        assert result.label == 'neutral'

    def test_model_returns_none_returns_neutral(self, svc):
        """TC-36: 模型返回 None 时返回 neutral 不崩溃"""
        svc.model.generate.return_value = None
        result = svc.analyze(make_audio())
        assert result.label == 'neutral'
```

### 验收标准汇总

| ID | 分类 | 描述 | 通过条件 |
|----|------|------|----------|
| TC-01 | 前置 | 过短音频跳过推理 | model 未被调用，返回 neutral |
| TC-02 | 前置 | 临界时长触发推理 | model.generate 被调用一次 |
| TC-03 | 前置 | Int16 正常处理 | 标签合法，不报错 |
| TC-04 | 前置 | 超长音频截取 | 传入 model 的数据长度 ≤ max |
| TC-05 | 预处理 | Float32 类型保持 | dtype == float32 |
| TC-06 | 预处理 | Int16 转换 | dtype == float32 |
| TC-07 | 预处理 | 裁剪生效 | max ≤ 1.0，min ≥ -1.0 |
| TC-08 | 过滤 | 低置信度降级 | label == neutral |
| TC-09 | 过滤 | 高置信度保留 | label == sad |
| TC-10 | 过滤 | 边界值保留 | label == happy |
| TC-11 | 规范化 | 中文 happy | 映射正确 |
| TC-12 | 规范化 | 中文 sad | 映射正确 |
| TC-13 | 规范化 | 英文变体 | 映射正确 |
| TC-14 | 规范化 | 未知标签 | 映射为 neutral |
| TC-15 | 规范化 | 标准标签自映射 | 7 个标签均正确 |
| TC-16 | 平滑 | 无历史返回当前 | label 和 score 不变 |
| TC-17 | 平滑 | 误判抑制 | 平滑后仍为 happy |
| TC-18 | 平滑 | 一致情绪保留 | 平滑后仍为 sad |
| TC-19 | 平滑 | 分数不超 1.0 | score ≤ 1.0 |
| TC-20 | 趋势 | 无历史提示 | 含「首次对话」 |
| TC-21 | 趋势 | 好转检测 | 含「好转」 |
| TC-22 | 趋势 | 下降检测 | 含「下降」 |
| TC-23 | 趋势 | 稳定检测 | 含「稳定」 |
| TC-24 | 趋势 | 中文标签 | 不含英文标签 |
| TC-25 | 会话 | reset 清空 | len == 0 |
| TC-26 | 会话 | 窗口限制 | len == WINDOW |
| TC-27 | 会话 | analyze 更新历史 | len += 1 |
| TC-28 | 输出 | 字段完整 | 9 个字段均存在 |
| TC-29 | 输出 | valence 范围 | [0.0, 1.0] |
| TC-30 | 输出 | arousal 范围 | [0.0, 1.0] |
| TC-31 | 输出 | 中文标签非空 | 含中文字符 |
| TC-32 | 输出 | history 类型 | isinstance list |
| TC-33 | 输出 | 7 种坐标完整 | 均在 [0,1] 内 |
| TC-34 | 异常 | 模型异常回退 | 返回 neutral |
| TC-35 | 异常 | 空 scores 回退 | 返回 neutral |
| TC-36 | 异常 | None 返回回退 | 返回 neutral |
