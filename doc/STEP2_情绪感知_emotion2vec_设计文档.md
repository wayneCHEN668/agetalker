# STEP 2 — 情绪感知模块
**技术栈：emotion2vec_plus_large（阿里开源）本地 CPU 推理**

---

## 目录
1. [模块概述](#1-模块概述)
2. [心理学理论基础](#2-心理学理论基础)
3. [系统架构](#3-系统架构)
4. [环境依赖与安装](#4-环境依赖与安装)
5. [情绪标签体系设计](#5-情绪标签体系设计)
6. [核心实现代码](#6-核心实现代码)
7. [情绪历史平滑策略](#7-情绪历史平滑策略)
8. [HTTP API 接口规范](#8-http-api-接口规范)
9. [性能优化](#9-性能优化cpu-环境)
10. [TDD 验收测试](#10-tdd-验收测试)

---

## 1. 模块概述

本模块接收 STEP 1 产生的**每句完整 PCM 音频**，通过 `emotion2vec_plus_large` 模型提取声学情绪特征，输出情绪类别标签及置信度分数。同时维护**多轮情绪历史窗口**，通过加权平均消除单句误判，为 STEP 3 提供稳定可靠的情绪上下文。

### 目标指标

| 指标 | 目标值 |
|------|--------|
| 单次推理延迟（CPU） | ≤ 500ms |
| 情绪分类准确率 | ≥ 80%（纯声学特征基线） |
| 置信度阈值 | < 0.45 时自动降级为 neutral |
| 历史平滑窗口 | 最近 3 轮加权平均 |
| 情绪跳变抑制 | 相邻轮次情绪剧烈变化时触发平滑 |

### 与其他模块的关系

```
STEP 1 ──→ STEP 2 ──→ STEP 3
  转录文本         情绪标签
  PCM 音频    +    置信度        ──→  LLM 心理回复
                  valence
                  arousal
                  情绪历史
```

---

## 2. 心理学理论基础

### 2.1 Russell 环形情感模型（Circumplex Model of Affect）

emotion2vec 的情绪分类基于 Russell（1980）提出的**二维环形情感空间**，本系统使用该模型的两个核心维度为 STEP 3 的回复策略提供量化输入：

```
         高唤醒 (Arousal=1.0)
              ↑
    愤怒       |       快乐
  (angry)     |     (happy)
              |
负效价 ←──────┼──────→ 正效价
(Valence=0)   |       (Valence=1.0)
              |
    悲伤       |       平静
    (sad)      |     (neutral)
              ↓
         低唤醒 (Arousal=0.0)
```

- **Valence（效价）**：情绪的正负性，0.0 = 极负面，1.0 = 极正面
- **Arousal（唤醒度）**：情绪的激活程度，0.0 = 低唤醒，1.0 = 高唤醒

这两个维度会作为结构化字段传给 STEP 3，使 LLM 在构建回复策略时拥有**定量的情绪坐标**，而不仅是模糊的文字标签。

### 2.2 为什么只用声学特征（不融合文本）

| 方案 | 优势 | 劣势 | 本系统选择 |
|------|------|------|-----------|
| 纯声学（emotion2vec） | 捕捉语调、音色、语速等潜意识情绪 | 受噪音影响 | ✅ 主模型 |
| 纯文本（NLP分类） | 语义准确 | 老人表达含蓄，字面情绪弱 | ❌ |
| 声学+文本融合 | 准确率最高 | 延迟加倍，结构复杂 | ❌（可迭代加入）|

> **设计决策**：老年人的真实情绪往往体现在**语调和语速**上，而非字面措辞。声学模型对此更敏感，且单模型架构维护成本低。

---

## 3. 系统架构

### 3.1 数据流

```
STEP 1 事件: ASR_TRANSCRIPT_READY
  { text, audio_b64, duration_ms, timestamp }
          │
          ▼
EmotionService.analyze(audio, sample_rate)
  │
  ├─ 1. 前置校验
  │      ├─ 音频时长 < 0.5s  →  返回 neutral（跳过推理）
  │      └─ 采样率校验（必须 16kHz）
  │
  ├─ 2. 音频预处理
  │      ├─ Int16 → Float32 归一化
  │      └─ 幅值裁剪防止削波
  │
  ├─ 3. emotion2vec_plus_large 推理
  │      └─ 输出: [ {label, score}, ... ]  全部7类得分
  │
  ├─ 4. 置信度过滤
  │      └─ top1 score < 0.45  →  label 强制改为 neutral
  │
  ├─ 5. 标签规范化
  │      └─ 中文标签 / 英文变体  →  统一英文标准标签
  │
  ├─ 6. 情绪历史平滑（滑动窗口 N=3）
  │      └─ 加权投票：当前×0.5 + 上轮×0.3 + 上上轮×0.2
  │
  └─ 7. 输出 EmotionResult
           { label, score, smoothed_label, smoothed_score,
             valence, arousal, trend, history }
          │
          ▼
    发布事件: EMOTION_ANALYZED
    → STEP 3 消费
```

### 3.2 跨模块事件

```
STEP 2 发出事件:

  EMOTION_ANALYZED
  {
    label: string,           // 平滑后情绪标签（英文）
    label_zh: string,        // 平滑后情绪标签（中文）
    score: float,            // 平滑后置信度 0-1
    raw_label: string,       // 模型原始输出标签
    raw_score: float,        // 模型原始置信度
    valence: float,          // Russell 效价 0-1
    arousal: float,          // Russell 唤醒度 0-1
    trend: string,           // 情绪趋势描述（供 LLM 使用）
    history: [               // 最近 3 轮原始情绪
      { label, score },
      ...
    ]
  }
```

---

## 4. 环境依赖与安装

### 4.1 Python 依赖

```
# requirements_step2.txt
funasr>=1.1.0          # emotion2vec 通过 FunASR 框架加载
torch>=2.0.0           # CPU 推理
numpy>=1.24.0
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
pydantic>=2.0.0
```

```bash
pip install -r requirements_step2.txt
```

### 4.2 模型选型对比

| 模型 | 大小 | CPU 推理延迟 | 准确率 | 推荐场景 |
|------|------|-------------|--------|----------|
| `emotion2vec_plus_large` | ~300MB | ~400ms | 最高 | **生产推荐** |
| `emotion2vec_plus_base` | ~90MB | ~150ms | 较高 | 低配机器备选 |
| `emotion2vec_plus_seed` | ~25MB | ~80ms | 一般 | 极低延迟场景 |

> **默认使用 `emotion2vec_plus_large`**，若 CPU 推理超时，可降级为 `emotion2vec_plus_base`，在配置文件中修改 `EMOTION_MODEL` 变量即可。

### 4.3 模型下载

```python
from funasr import AutoModel

# 首次运行自动从 ModelScope 下载，缓存至 ~/.cache/modelscope/
model = AutoModel(
    model='iic/emotion2vec_plus_large',
    device='cpu',
    disable_update=True,
)
```

---

## 5. 情绪标签体系设计

### 5.1 标准情绪标签（7类）

| 英文标签 | 中文含义 | Valence | Arousal | 声学特征 |
|----------|----------|---------|---------|----------|
| `neutral` | 平静/中性 | 0.50 | 0.20 | 语速平稳、音调均匀、音量适中 |
| `happy` | 快乐/喜悦 | 0.90 | 0.70 | 语调上扬、语速加快、音量偏大 |
| `sad` | 悲伤 | 0.10 | 0.20 | 语调低沉、语速缓慢、气声明显 |
| `angry` | 愤怒 | 0.10 | 0.90 | 音量大、语速快、音调高且变化剧烈 |
| `fearful` | 恐惧/焦虑 | 0.15 | 0.80 | 颤音、语速不稳、语气词增多 |
| `disgusted` | 厌恶 | 0.15 | 0.50 | 鼻音重、短促停顿、语调平坦偏低 |
| `surprised` | 惊讶 | 0.60 | 0.85 | 音量突变、语调急剧变化 |

### 5.2 标签规范化映射

emotion2vec 模型输出的标签可能为中文或不同英文变体，统一规范化为上表标准标签：

```python
LABEL_NORMALIZE_MAP = {
    # 中文标签
    '开心': 'happy',   '高兴': 'happy',   '愉快': 'happy',
    '悲伤': 'sad',     '难过': 'sad',     '伤心': 'sad',
    '愤怒': 'angry',   '生气': 'angry',
    '恐惧': 'fearful', '害怕': 'fearful', '焦虑': 'fearful',
    '厌恶': 'disgusted',
    '惊讶': 'surprised',
    '中性': 'neutral', '平静': 'neutral',
    # 英文变体
    'happy': 'happy', 'joy': 'happy',
    'sad': 'sad', 'sadness': 'sad',
    'angry': 'angry', 'anger': 'angry',
    'fearful': 'fearful', 'fear': 'fearful', 'anxious': 'fearful',
    'disgusted': 'disgusted', 'disgust': 'disgusted',
    'surprised': 'surprised', 'surprise': 'surprised',
    'neutral': 'neutral',
}
```

---

## 6. 核心实现代码

### 6.1 目录结构

```
step2_emotion/
├── emotion_service.py    # 核心情绪识别服务
├── emotion_server.py     # FastAPI HTTP 服务
├── config.py             # 配置常量
├── requirements_step2.txt
└── tests/
    └── test_step2.py
```

### 6.2 配置文件 `config.py`

```python
# config.py

# 模型配置
EMOTION_MODEL = 'iic/emotion2vec_plus_large'   # 可改为 plus_base 降低延迟
DEVICE = 'cpu'

# 推理参数
CONFIDENCE_THRESHOLD = 0.45   # 低于此置信度降级为 neutral
MIN_AUDIO_DURATION_S = 0.5    # 低于此时长跳过推理（秒）
MAX_AUDIO_DURATION_S = 10.0   # 超过此时长截取末尾片段（秒）

# 历史平滑
HISTORY_WINDOW = 3            # 滑动窗口大小
HISTORY_WEIGHTS = [0.50, 0.30, 0.20]  # 从新到旧的权重

# Russell 情绪坐标映射
EMOTION_COORDS = {
    'neutral':   {'valence': 0.50, 'arousal': 0.20},
    'happy':     {'valence': 0.90, 'arousal': 0.70},
    'sad':       {'valence': 0.10, 'arousal': 0.20},
    'angry':     {'valence': 0.10, 'arousal': 0.90},
    'fearful':   {'valence': 0.15, 'arousal': 0.80},
    'disgusted': {'valence': 0.15, 'arousal': 0.50},
    'surprised': {'valence': 0.60, 'arousal': 0.85},
}

# 中文标签映射（用于 STEP 3 Prompt 填充）
EMOTION_ZH_MAP = {
    'neutral':   '平静',
    'happy':     '快乐',
    'sad':       '悲伤',
    'angry':     '愤怒',
    'fearful':   '焦虑/恐惧',
    'disgusted': '厌恶',
    'surprised': '惊讶',
}

# 标签规范化映射
LABEL_NORMALIZE_MAP = {
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
```

### 6.3 核心服务 `emotion_service.py`

```python
import numpy as np
import logging
import torch
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from funasr import AutoModel
from config import (
    EMOTION_MODEL, DEVICE, CONFIDENCE_THRESHOLD,
    MIN_AUDIO_DURATION_S, MAX_AUDIO_DURATION_S,
    HISTORY_WINDOW, HISTORY_WEIGHTS,
    EMOTION_COORDS, EMOTION_ZH_MAP, LABEL_NORMALIZE_MAP,
)

logger = logging.getLogger(__name__)


# ─── 数据结构 ────────────────────────────────────────────────────────────────

@dataclass
class EmotionResult:
    # 模型原始输出
    raw_label: str
    raw_score: float

    # 平滑后结果（提供给 STEP 3）
    label: str              # 英文标签
    label_zh: str           # 中文标签
    score: float            # 置信度 0-1

    # Russell 情感坐标
    valence: float          # 效价 0-1
    arousal: float          # 唤醒度 0-1

    # 上下文信息
    trend: str              # 情绪趋势描述
    history: list           # 最近 N 轮原始情绪记录


# ─── 情绪服务 ────────────────────────────────────────────────────────────────

class EmotionService:

    def __init__(self):
        logger.info(f"正在加载情绪模型: {EMOTION_MODEL}")
        self.model = AutoModel(
            model=EMOTION_MODEL,
            device=DEVICE,
            disable_update=True,
        )
        # 推理线程数限制（CPU 环境）
        torch.set_num_threads(4)
        self.history: deque = deque(maxlen=HISTORY_WINDOW)
        logger.info("情绪模型加载完成 ✅")


    # ── 主入口 ───────────────────────────────────────────────────────────────

    def analyze(self, audio: np.ndarray, sample_rate: int = 16000) -> EmotionResult:
        """
        对单句音频进行情绪分析。

        Args:
            audio:       Float32 归一化 PCM，或 Int16 原始 PCM
            sample_rate: 采样率，必须为 16000

        Returns:
            EmotionResult
        """
        # 1. 前置校验
        audio = self._preprocess(audio, sample_rate)
        duration = len(audio) / sample_rate

        if duration < MIN_AUDIO_DURATION_S:
            logger.debug(f"音频过短 ({duration:.2f}s)，返回 neutral")
            return self._make_neutral("音频过短，跳过推理")

        # 超长音频取末尾片段（老人通常句末情绪更明显）
        if duration > MAX_AUDIO_DURATION_S:
            max_samples = int(MAX_AUDIO_DURATION_S * sample_rate)
            audio = audio[-max_samples:]
            logger.debug(f"音频超长，截取末尾 {MAX_AUDIO_DURATION_S}s")

        # 2. 模型推理
        try:
            raw_scores = self._run_inference(audio, sample_rate)
        except Exception as e:
            logger.error(f"情绪推理失败: {e}")
            return self._make_neutral(f"推理异常: {e}")

        # 3. 解析 top1 结果
        if not raw_scores:
            return self._make_neutral("模型无输出")

        top1 = max(raw_scores, key=lambda x: x['score'])
        raw_label = self._normalize_label(top1['label'])
        raw_score = float(top1['score'])

        logger.debug(f"原始情绪: {raw_label} ({raw_score:.2f})")

        # 4. 置信度过滤：低置信度降级为 neutral
        if raw_score < CONFIDENCE_THRESHOLD:
            logger.debug(f"置信度不足 ({raw_score:.2f} < {CONFIDENCE_THRESHOLD})，降级为 neutral")
            final_label = 'neutral'
            final_score = 1.0 - raw_score   # 反转作为 neutral 的置信度
        else:
            final_label = raw_label
            final_score = raw_score

        # 5. 历史平滑
        smoothed = self._smooth(final_label, final_score)

        # 6. 更新历史
        self.history.append({'label': final_label, 'score': final_score})

        # 7. 计算趋势
        trend = self._compute_trend()

        # 8. 查坐标
        coords = EMOTION_COORDS[smoothed['label']]

        return EmotionResult(
            raw_label=raw_label,
            raw_score=raw_score,
            label=smoothed['label'],
            label_zh=EMOTION_ZH_MAP[smoothed['label']],
            score=round(smoothed['score'], 3),
            valence=coords['valence'],
            arousal=coords['arousal'],
            trend=trend,
            history=list(self.history),
        )


    # ── 内部方法 ─────────────────────────────────────────────────────────────

    def _preprocess(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """统一转为 Float32，进行幅值裁剪。"""
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # 防止削波：将超出范围的值裁剪到 [-1, 1]
        audio = np.clip(audio, -1.0, 1.0)
        return audio


    def _run_inference(self, audio: np.ndarray, sample_rate: int) -> list:
        """
        调用 emotion2vec 模型推理。

        返回格式:
            [ {'label': str, 'score': float}, ... ]  # 全部类别得分
        """
        result = self.model.generate(
            input=audio,
            sample_rate=sample_rate,
            output_dir=None,
            granularity='utterance',   # 句级情绪（非帧级）
            extract_embedding=False,   # 不需要嵌入向量
        )

        if not result or 'scores' not in result[0]:
            return []

        # result[0]['scores'] 格式: [ {'label': str, 'score': float}, ... ]
        return result[0]['scores']


    def _normalize_label(self, raw: str) -> str:
        """将模型输出的任意标签规范化为标准英文标签。"""
        normalized = LABEL_NORMALIZE_MAP.get(raw.strip())
        if normalized is None:
            logger.warning(f"未知情绪标签: '{raw}'，映射为 neutral")
            return 'neutral'
        return normalized


    def _smooth(self, current_label: str, current_score: float) -> dict:
        """
        加权历史平滑。
        用最近 N 轮情绪的带权票数选出最终情绪，
        抑制单次误判导致的情绪剧烈跳变。
        """
        if not self.history:
            return {'label': current_label, 'score': current_score}

        # 统计带权票数
        votes: dict[str, float] = {
            current_label: HISTORY_WEIGHTS[0] * current_score
        }

        hist_list = list(reversed(list(self.history)))   # 最新的在最前
        for i, h in enumerate(hist_list):
            if i + 1 >= len(HISTORY_WEIGHTS):
                break
            w = HISTORY_WEIGHTS[i + 1]
            label = h['label']
            votes[label] = votes.get(label, 0.0) + w * h['score']

        winner = max(votes, key=votes.get)
        winner_score = min(1.0, votes[winner])   # 归一化到 1.0 以内

        return {'label': winner, 'score': winner_score}


    def _compute_trend(self) -> str:
        """
        根据情绪历史计算趋势描述字符串，填入 STEP 3 的 System Prompt。
        """
        hist = list(self.history)

        if len(hist) < 2:
            return "首次对话，情绪基线未建立"

        prev_label = hist[-2]['label'] if len(hist) >= 2 else 'neutral'
        curr_label = hist[-1]['label']

        prev_v = EMOTION_COORDS.get(prev_label, {}).get('valence', 0.5)
        curr_v = EMOTION_COORDS.get(curr_label, {}).get('valence', 0.5)
        delta = curr_v - prev_v

        prev_zh = EMOTION_ZH_MAP.get(prev_label, prev_label)
        curr_zh = EMOTION_ZH_MAP.get(curr_label, curr_label)

        if delta > 0.30:
            return f"情绪明显好转（{prev_zh} → {curr_zh}）"
        elif delta < -0.30:
            return f"情绪明显下降（{prev_zh} → {curr_zh}）"
        elif curr_label == prev_label:
            return f"情绪持续稳定在「{curr_zh}」状态"
        else:
            return f"情绪平稳波动（{prev_zh} → {curr_zh}）"


    def _make_neutral(self, reason: str = "") -> EmotionResult:
        """返回默认 neutral 结果（用于各类异常回退）。"""
        if reason:
            logger.debug(f"返回 neutral，原因: {reason}")
        coords = EMOTION_COORDS['neutral']
        return EmotionResult(
            raw_label='neutral',
            raw_score=1.0,
            label='neutral',
            label_zh='平静',
            score=1.0,
            valence=coords['valence'],
            arousal=coords['arousal'],
            trend=self._compute_trend() if self.history else "首次对话，情绪基线未建立",
            history=list(self.history),
        )


    def reset(self):
        """新对话开始时调用，清除情绪历史。"""
        self.history.clear()
        logger.info("情绪历史已重置")


    def to_dict(self, result: EmotionResult) -> dict:
        """将 EmotionResult 序列化为字典，供 HTTP API 返回。"""
        return {
            'label':      result.label,
            'label_zh':   result.label_zh,
            'score':      result.score,
            'raw_label':  result.raw_label,
            'raw_score':  result.raw_score,
            'valence':    result.valence,
            'arousal':    result.arousal,
            'trend':      result.trend,
            'history':    result.history,
        }
```

### 6.4 HTTP 服务 `emotion_server.py`

```python
import base64
import asyncio
import logging
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from emotion_service import EmotionService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Emotion Service - STEP 2")
svc = EmotionService()


# ─── 请求/响应 Schema ────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    audio_b64: str = Field(..., description="Base64 编码的 Int16 PCM 音频数据")
    sample_rate: int = Field(default=16000, description="采样率，必须为 16000")
    session_id: str = Field(..., description="会话 ID，用于多用户隔离（当前单例）")


class ResetRequest(BaseModel):
    session_id: str


# ─── 路由 ────────────────────────────────────────────────────────────────────

@app.post('/emotion/analyze')
async def analyze(req: AnalyzeRequest):
    """
    对单句音频进行情绪分析。
    接收 STEP 1 的 audio_b64 字段，返回情绪结果。
    """
    try:
        raw_bytes = base64.b64decode(req.audio_b64)
        audio = np.frombuffer(raw_bytes, dtype=np.int16)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"音频解码失败: {e}")

    # 在线程池中执行 CPU 推理，避免阻塞事件循环
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: svc.analyze(audio, req.sample_rate)
    )

    return svc.to_dict(result)


@app.post('/emotion/reset')
async def reset(req: ResetRequest):
    """重置情绪历史，用于新对话开始时调用。"""
    svc.reset()
    return {'status': 'ok', 'session_id': req.session_id}


@app.get('/emotion/history')
async def get_history():
    """获取当前情绪历史（调试用）。"""
    return {'history': list(svc.history)}


@app.get('/health')
async def health():
    return {'status': 'ok', 'model': 'emotion2vec_plus_large'}
```

---

## 7. 情绪历史平滑策略

### 7.1 设计动机

老年人语音存在以下特点，容易导致情绪**单帧误判**：

- 气声、颤音可能被误判为 `fearful`
- 语速加快（激动讲故事）可能被误判为 `angry`
- 停顿过多导致音频能量不均

通过**3轮加权滑动窗口**投票，可有效抑制单次误判带来的情绪突变。

### 7.2 平滑算法图示

```
轮次:    第1轮      第2轮      第3轮（当前）
标签:    happy      happy      angry
置信度:  0.82       0.78       0.61

权重:    0.20       0.30       0.50

─────────────────────────────────────────

带权票数:
  happy = 0.20×0.82 + 0.30×0.78 = 0.164 + 0.234 = 0.398
  angry = 0.50×0.61             = 0.305

最终结果: happy（0.398 > 0.305）✅
→ 成功抑制了一次 angry 的误判
```

### 7.3 需要调整平滑参数的场景

| 场景 | 问题 | 调整方案 |
|------|------|----------|
| 情绪变化很快的老人 | 平滑导致情绪响应滞后 | 将当前权重从 0.50 提高到 0.65 |
| 噪音环境较差 | 误判频繁，平滑不够 | 窗口扩大到 5，提高 CONFIDENCE_THRESHOLD 到 0.55 |
| 情绪持续低落 | 需要更快响应 | 降低 CONFIDENCE_THRESHOLD 到 0.40 |

---

## 8. HTTP API 接口规范

### POST `/emotion/analyze`

**请求体：**
```json
{
  "audio_b64": "<Base64 encoded Int16 PCM>",
  "sample_rate": 16000,
  "session_id": "user_001"
}
```

**成功响应（200）：**
```json
{
  "label": "sad",
  "label_zh": "悲伤",
  "score": 0.718,
  "raw_label": "sad",
  "raw_score": 0.731,
  "valence": 0.10,
  "arousal": 0.20,
  "trend": "情绪持续稳定在「悲伤」状态",
  "history": [
    { "label": "neutral", "score": 0.682 },
    { "label": "sad",     "score": 0.611 },
    { "label": "sad",     "score": 0.731 }
  ]
}
```

**错误响应（400）：**
```json
{
  "detail": "音频解码失败: Invalid base64 data"
}
```

### POST `/emotion/reset`

```json
// 请求
{ "session_id": "user_001" }

// 响应
{ "status": "ok", "session_id": "user_001" }
```

---

## 9. 性能优化（CPU 环境）

| 优化项 | 方案 | 效果 |
|--------|------|------|
| **模型降级** | large → base | 延迟从 ~400ms 降至 ~150ms，精度略低 |
| **线程控制** | `torch.set_num_threads(4)` | 防止线程过多竞争 |
| **音频截断** | 超过 10s 取末尾片段 | 避免长音频推理超时 |
| **异步执行** | `run_in_executor` | 推理不阻塞 WebSocket 接收 |
| **服务启动预热** | 启动时用静音音频跑一次推理 | 避免首次请求延迟过高 |

### 服务启动预热代码

```python
# 在 emotion_server.py 的 startup 事件中加入
@app.on_event("startup")
async def warmup():
    logger.info("执行模型预热...")
    dummy_audio = np.zeros(16000, dtype=np.int16)  # 1s 静音
    svc.analyze(dummy_audio)
    logger.info("预热完成 ✅")
```

---

## 10. TDD 验收测试

### 测试文件 `tests/test_step2.py`

```python
import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from collections import deque

from emotion_service import EmotionService, EmotionResult
from config import CONFIDENCE_THRESHOLD, MIN_AUDIO_DURATION_S, EMOTION_COORDS


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    """每个测试用例使用独立的 EmotionService 实例"""
    with patch('emotion_service.AutoModel') as mock_model_cls:
        mock_model_cls.return_value = MagicMock()
        service = EmotionService()
        service.model = mock_model_cls.return_value
    return service


def make_audio(duration_s: float = 2.0, dtype=np.float32) -> np.ndarray:
    """生成测试用音频（正弦波）"""
    samples = int(16000 * duration_s)
    t = np.linspace(0, duration_s, samples)
    audio = (np.sin(2 * np.pi * 440 * t) * 0.3).astype(dtype)
    return audio


def mock_scores(label: str, score: float) -> list:
    """构造 emotion2vec 风格的 scores 输出"""
    all_labels = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']
    remaining = (1.0 - score) / (len(all_labels) - 1)
    return [
        {'label': l, 'score': score if l == label else remaining}
        for l in all_labels
    ]


# ─── TC-01: 前置校验 ──────────────────────────────────────────────────────────

class TestPrecheck:

    def test_short_audio_returns_neutral(self, svc):
        """TC-01: 音频时长 < 0.5s 时直接返回 neutral，不调用模型"""
        short_audio = make_audio(duration_s=0.3)
        result = svc.analyze(short_audio)
        assert result.label == 'neutral'
        svc.model.generate.assert_not_called()

    def test_exactly_threshold_audio_runs_inference(self, svc):
        """TC-02: 音频时长 = MIN_AUDIO_DURATION_S 时正常执行推理"""
        svc.model.generate.return_value = [{'scores': mock_scores('neutral', 0.8)}]
        audio = make_audio(duration_s=MIN_AUDIO_DURATION_S)
        svc.analyze(audio)
        svc.model.generate.assert_called_once()

    def test_int16_audio_accepted(self, svc):
        """TC-03: Int16 类型音频被正确转换，不报错"""
        svc.model.generate.return_value = [{'scores': mock_scores('neutral', 0.8)}]
        audio_int16 = make_audio(duration_s=2.0, dtype=np.int16)
        result = svc.analyze(audio_int16)
        assert result.label in ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']


# ─── TC-02: 置信度过滤 ────────────────────────────────────────────────────────

class TestConfidenceFilter:

    def test_low_confidence_falls_back_to_neutral(self, svc):
        """TC-04: 置信度 < CONFIDENCE_THRESHOLD 时强制降级为 neutral"""
        low_score = CONFIDENCE_THRESHOLD - 0.05
        svc.model.generate.return_value = [{'scores': mock_scores('angry', low_score)}]
        result = svc.analyze(make_audio())
        assert result.label == 'neutral'

    def test_above_threshold_keeps_label(self, svc):
        """TC-05: 置信度 >= CONFIDENCE_THRESHOLD 时保留原始标签"""
        high_score = CONFIDENCE_THRESHOLD + 0.10
        svc.model.generate.return_value = [{'scores': mock_scores('sad', high_score)}]
        result = svc.analyze(make_audio())
        # 无历史时，label 应为 sad
        assert result.label == 'sad'


# ─── TC-03: 标签规范化 ────────────────────────────────────────────────────────

class TestLabelNormalization:

    def test_chinese_label_normalized(self, svc):
        """TC-06: 中文标签正确映射为英文标准标签"""
        svc.model.generate.return_value = [{'scores': [
            {'label': '开心', 'score': 0.85},
            {'label': '中性', 'score': 0.15},
        ]}]
        result = svc.analyze(make_audio())
        assert result.raw_label == 'happy'

    def test_unknown_label_maps_to_neutral(self, svc):
        """TC-07: 未知标签映射为 neutral"""
        normalized = svc._normalize_label('未知情绪xyz')
        assert normalized == 'neutral'


# ─── TC-04: 历史平滑 ─────────────────────────────────────────────────────────

class TestHistorySmoothing:

    def test_single_misclassification_suppressed(self, svc):
        """TC-08: 两轮 happy 后单次 angry（低分），平滑结果仍为 happy"""
        svc.history.append({'label': 'happy', 'score': 0.85})
        svc.history.append({'label': 'happy', 'score': 0.80})
        result = svc._smooth('angry', 0.52)
        assert result['label'] == 'happy'

    def test_consistent_emotion_wins(self, svc):
        """TC-09: 三轮一致的情绪，平滑结果保持不变"""
        svc.history.append({'label': 'sad', 'score': 0.75})
        svc.history.append({'label': 'sad', 'score': 0.78})
        result = svc._smooth('sad', 0.80)
        assert result['label'] == 'sad'

    def test_empty_history_returns_current(self, svc):
        """TC-10: 无历史时直接返回当前结果"""
        result = svc._smooth('happy', 0.90)
        assert result['label'] == 'happy'
        assert result['score'] == 0.90


# ─── TC-05: 情绪历史与趋势 ───────────────────────────────────────────────────

class TestTrendAndHistory:

    def test_trend_improvement(self, svc):
        """TC-11: 情绪从 sad 变为 happy，趋势描述含「好转」"""
        svc.history.append({'label': 'sad', 'score': 0.70})
        svc.history.append({'label': 'happy', 'score': 0.80})
        trend = svc._compute_trend()
        assert '好转' in trend

    def test_trend_decline(self, svc):
        """TC-12: 情绪从 happy 变为 sad，趋势描述含「下降」"""
        svc.history.append({'label': 'happy', 'score': 0.80})
        svc.history.append({'label': 'sad', 'score': 0.75})
        trend = svc._compute_trend()
        assert '下降' in trend

    def test_trend_stable(self, svc):
        """TC-13: 情绪连续两轮相同，趋势描述含「稳定」"""
        svc.history.append({'label': 'neutral', 'score': 0.70})
        svc.history.append({'label': 'neutral', 'score': 0.72})
        trend = svc._compute_trend()
        assert '稳定' in trend

    def test_reset_clears_history(self, svc):
        """TC-14: reset 后历史为空"""
        svc.history.append({'label': 'happy', 'score': 0.8})
        svc.reset()
        assert len(svc.history) == 0


# ─── TC-06: 输出格式完整性 ───────────────────────────────────────────────────

class TestOutputFormat:

    def test_all_required_fields_present(self, svc):
        """TC-15: EmotionResult 包含 STEP 3 所需全部字段"""
        svc.model.generate.return_value = [{'scores': mock_scores('happy', 0.80)}]
        result = svc.analyze(make_audio())
        d = svc.to_dict(result)

        required = ['label', 'label_zh', 'score', 'raw_label',
                    'raw_score', 'valence', 'arousal', 'trend', 'history']
        for field in required:
            assert field in d, f"缺少字段: {field}"

    def test_valence_arousal_in_range(self, svc):
        """TC-16: valence 和 arousal 值在 [0, 1] 范围内"""
        svc.model.generate.return_value = [{'scores': mock_scores('angry', 0.75)}]
        result = svc.analyze(make_audio())
        assert 0.0 <= result.valence <= 1.0
        assert 0.0 <= result.arousal <= 1.0

    def test_label_zh_is_chinese(self, svc):
        """TC-17: label_zh 为非空中文字符串"""
        svc.model.generate.return_value = [{'scores': mock_scores('sad', 0.80)}]
        result = svc.analyze(make_audio())
        assert result.label_zh
        assert any('\u4e00' <= c <= '\u9fff' for c in result.label_zh)
```

### 验收标准汇总

| 测试用例 | 描述 | 通过条件 |
|----------|------|----------|
| TC-01 | 过短音频跳过推理 | 返回 neutral，model 未被调用 |
| TC-02 | 临界时长正常推理 | model.generate 被调用一次 |
| TC-03 | Int16 音频正常处理 | 无异常，标签合法 |
| TC-04 | 低置信度降级 | label == neutral |
| TC-05 | 高置信度保留 | label == sad |
| TC-06 | 中文标签规范化 | raw_label == happy |
| TC-07 | 未知标签处理 | 映射为 neutral |
| TC-08 | 误判抑制 | 平滑结果为 happy |
| TC-09 | 一致情绪保留 | 平滑结果为 sad |
| TC-10 | 无历史直接返回 | label == happy |
| TC-11 | 情绪好转趋势 | trend 含「好转」 |
| TC-12 | 情绪下降趋势 | trend 含「下降」 |
| TC-13 | 情绪稳定趋势 | trend 含「稳定」 |
| TC-14 | reset 清空历史 | history 长度为 0 |
| TC-15 | 输出字段完整 | 所有必填字段存在 |
| TC-16 | 坐标值合法 | 均在 [0, 1] 内 |
| TC-17 | 中文标签非空 | 含中文字符 |

---

## 附录：启动命令

```bash
# 开发模式
uvicorn emotion_server:app --host 0.0.0.0 --port 8001 --reload

# 生产模式
uvicorn emotion_server:app --host 0.0.0.0 --port 8001 --workers 1
```

> ⚠️ `workers=1`：EmotionService 维护情绪历史状态，多进程会导致历史丢失。若需多用户并发，需为每个 `session_id` 维护独立的 EmotionService 实例。
