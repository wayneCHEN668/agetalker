# STEP 4 — 情绪语音合成模块
**架构：单应用合并版 · CosyVoice TTS API · 流式 PCM 播放 · 端口 8000**

---

## 目录
1. [模块概述](#1-模块概述)
2. [治愈性对称原则](#2-治愈性对称原则)
3. [在单应用中的位置](#3-在单应用中的位置)
4. [目录结构](#4-目录结构)
5. [配置常量](#5-配置常量)
6. [核心服务实现](#6-核心服务实现)
7. [路由层实现](#7-路由层实现)
8. [回声消除协议](#8-回声消除协议)
9. [LLM-TTS 流水线并行](#9-llm-tts-流水线并行)
10. [HTTP 接口规范](#10-http-接口规范)
11. [前端集成代码](#11-前端集成代码)
12. [全链路时序图](#12-全链路时序图)
13. [TDD 验收测试](#13-tdd-验收测试)

---

## 1. 模块概述

本模块接收 **STEP 3 输出的回复文本**和 **TTS 情绪参数**（均来自 SSE `done` 事件），调用**通义千问 CosyVoice TTS API** 生成带情绪色彩的语音，以流式 PCM 传输至前端通过 WebAudio API 播放。

同时解决两个关键工程问题：
- **回声消除**：TTS 播放期间暂停麦克风发送，防止 AI 声音被 STEP 1 误识别
- **流水线并行**：STEP 3 输出首个完整句子时立即触发本模块合成，不等全文生成完毕

### 与旧版（独立端口 8003）的核心区别

| 维度 | 旧版（独立端口 8003） | 新版（单应用合并） |
|------|---------------------|------------------|
| 服务初始化 | 路由文件内自行初始化 | **main.py 统一初始化后注入** |
| 路由挂载 | 独立 FastAPI 应用 | **注册到主应用同一个端口** |
| 启动命令 | 独立一条 uvicorn | **随整个应用一起启动** |
| 前端请求地址 | `http://localhost:8003/tts/stream` | **`http://localhost:8000/tts/stream`** |

### 目标指标

| 指标 | 目标值 |
|------|--------|
| 首句播放延迟 | STEP 3 推送首句后 ≤ 800ms 开始发声 |
| 音频格式 | PCM 24kHz 16bit 单声道 |
| 情绪覆盖 | 7 种情绪 + 危机模式，共 8 套参数 |
| 回声隔离 | TTS 播放期间 ASR 帧发送暂停，恢复延迟 200ms |
| 多句连续播放 | 队列调度，句间无明显卡顿 |

---

## 2. 治愈性对称原则

> **核心设计原则：TTS 情绪不镜像用户情绪，而是治愈性的对立平衡。**

用户悲伤时，AI 用温柔平静的声音陪伴；用户愤怒时，AI 用更慢更温和的语调降温。TTS 的声音本身就是治疗手段。

TTS 参数已在 STEP 3 的 `config.py` 中统一定义（`TTS_PARAMS_MAP`），由 STEP 3 的 `done` 事件携带传给前端，再由前端 POST 到本模块，形成完整的参数传递链：

```
STEP 2 情绪标签
    │
    ▼
STEP 3 TTS_PARAMS_MAP 查表
    │  { speed, pitch, style }
    ▼
SSE done 事件携带 tts_params
    │
    ▼
前端 POST /tts/stream
    │
    ▼
STEP 4 CosyVoice API
```

### 情绪 → TTS 参数对应关系

| 用户情绪 | 语速 | 音调 | 风格 | 设计理由 |
|----------|------|------|------|----------|
| `sad` 悲伤 | 0.85 | -2 | gentle | 慢速低调传递陪伴感 |
| `fearful` 焦虑 | 0.88 | -1 | calm | 平静语调引导降焦虑 |
| `angry` 愤怒 | 0.88 | -1 | gentle | 温和降温，绝不对峙 |
| `happy` 快乐 | 1.05 | +1 | cheerful | 与用户共鸣，强化积极情绪 |
| `disgusted` 厌恶 | 0.92 | -1 | calm | 平和接纳，不对立 |
| `surprised` 惊讶 | 1.00 | 0 | neutral | 先稳定再观察 |
| `neutral` 平静 | 1.00 | 0 | neutral | 维持自然节奏 |
| `_crisis` 危机 | 0.82 | -2 | gentle | 最平缓语调，传递安全感 |

---

## 3. 在单应用中的位置

```
main.py（应用入口）
  │
  ├── lifespan() 统一初始化
  │       └── TTSService()    ← 本模块服务实例
  │
  └── app.include_router()
          └── routers/stream_tts.py   ← 本模块路由
                  │
                  │  POST /tts/stream   （PCM 流式响应）
                  │  GET  /tts/status
                  │
                  └── TTSService.synthesize_stream(text, speed, pitch, style, emotion_label)
                              │
                              ├── 参数校验与裁剪
                              ├── 分句（长文本）
                              ├── 调用 CosyVoice API（流式）
                              └── yield PCM chunks → StreamingResponse
```

**数据流说明**：

```
前端 useLLM.ts
  │ onFirstSentence 回调触发（STEP 3 首句生成时）
  │  { text: "首句。", tts_params: {speed, pitch, style} }
  │
  ▼
前端 useTTS.ts
  │ POST /tts/stream  （同一个端口 8000）
  │  { text, speed, pitch, style, emotion_label }
  │
  ▼
routers/stream_tts.py
  │ StreamingResponse(TTSService.synthesize_stream(...))
  │
  ▼
前端 WebAudio API
  │ 流式接收 PCM → 精确调度播放
  │
  ▼
扬声器输出
```

---

## 4. 目录结构

```
emotion_companion/
├── main.py                     # TTSService 在此初始化并注入
├── config.py                   # STEP 4 相关配置在此定义
│                               # （TTS_PARAMS_MAP 已在 STEP 3 配置中定义，共用）
│
├── services/
│   └── tts_service.py          # ← STEP 4 核心实现（纯 Python 类）
│
├── routers/
│   └── stream_tts.py           # ← STEP 4 路由（流式 PCM 协议层）
│
└── tests/
    └── test_tts_service.py     # ← STEP 4 测试
```

---

## 5. 配置常量

```python
# config.py（STEP 4 相关部分）

# ── CosyVoice TTS API ─────────────────────────────────────────────────────────
# DASHSCOPE_API_KEY 与 STEP 3 共用同一个 Key，已在 STEP 3 配置中定义

TTS_MODEL        = 'cosyvoice-v1'
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
# 可在此修改各情绪对应音色，无需改动服务代码
TTS_EMOTION_VOICE_MAP = {
    'happy':     'longxiaoxia',    # 活泼音色匹配快乐情绪
    'neutral':   'longxiaochun',   # 默认温柔音色
    'sad':       'longxiaochun',
    'fearful':   'longxiaochun',
    'angry':     'longxiaochun',
    'disgusted': 'longxiaochun',
    'surprised': 'longxiaochun',
    '_crisis':   'longxiaochun',
}

# ── 分句阈值 ──────────────────────────────────────────────────────────────────
# 超过此长度的文本按标点分句，逐句合成，保证自然语气停顿
TTS_MAX_SENTENCE_LEN = 50
```

### 推荐音色

| 音色 ID | 名称 | 特点 | 推荐情绪 |
|---------|------|------|----------|
| `longxiaochun` | 龙小淳 | 温柔女声，亲切自然 | **默认，悲伤/焦虑/平静** |
| `longxiaoxia` | 龙小夏 | 活泼女声，语调轻快 | 快乐 |
| `longshuo` | 龙硕 | 沉稳男声，充满信赖感 | 可选：需要权威感时 |

---

## 6. 核心服务实现

### `services/tts_service.py`

```python
import re
import logging
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat
from typing import Generator
from config import (
    DASHSCOPE_API_KEY,
    TTS_MODEL,
    TTS_DEFAULT_VOICE,
    TTS_SPEED_MIN,
    TTS_SPEED_MAX,
    TTS_PITCH_MIN,
    TTS_PITCH_MAX,
    TTS_STYLE_MAP,
    TTS_EMOTION_VOICE_MAP,
    TTS_MAX_SENTENCE_LEN,
)

logger = logging.getLogger(__name__)
dashscope.api_key = DASHSCOPE_API_KEY

# 分句正则：在句末标点处切分，标点保留在句尾
_SENTENCE_SPLIT_RE = re.compile(r'([^。！？.!?]+[。！？.!?])')


class TTSService:
    """
    CosyVoice TTS 语音合成服务。

    设计说明：
    - 纯 Python 服务类，不包含任何路由/HTTP 逻辑
    - 在 main.py 的 lifespan() 中初始化，整个应用生命周期共享同一实例
    - synthesize_stream() 直接 yield PCM bytes，由路由层包装为 StreamingResponse
    - is_playing 状态标志供前端查询，也可通过 /tts/status 接口轮询
    - TTS 参数（speed/pitch/style）由 STEP 3 的 TTS_PARAMS_MAP 计算后传入，
      本模块无需感知情绪逻辑，只负责合成
    """

    def __init__(self):
        # 播放状态标志：True 表示正在合成/播放，供回声消除使用
        self.is_playing: bool = False
        logger.info("TTS 服务初始化完成 ✅")


    # ── 主入口：流式合成 ──────────────────────────────────────────────────────

    def synthesize_stream(
        self,
        text:          str,
        speed:         float = 1.0,
        pitch:         int   = 0,
        style:         str   = 'neutral',
        emotion_label: str   = 'neutral',
    ) -> Generator[bytes, None, None]:
        """
        流式语音合成，yield 原始 PCM bytes。
        音频格式：PCM 24kHz 16bit 单声道

        Args:
            text:          待合成文本（来自 STEP 3 SSE done 事件的首句或剩余文本）
            speed:         语速倍率（来自 STEP 3 TTS_PARAMS_MAP，已体现治愈性对称）
            pitch:         音调偏移，半音（同上）
            style:         情感风格（同上）
            emotion_label: 用户情绪标签（用于按情绪自动选择音色）

        Yields:
            bytes: 原始 PCM 音频块，前端 WebAudio API 直接解码播放
        """
        if not text or not text.strip():
            logger.debug("文本为空，跳过 TTS 合成")
            return

        # 参数范围裁剪（防越界）
        speed = max(TTS_SPEED_MIN, min(TTS_SPEED_MAX, float(speed)))
        pitch = max(TTS_PITCH_MIN, min(TTS_PITCH_MAX, int(pitch)))
        style = TTS_STYLE_MAP.get(style, 'neutral')
        voice = TTS_EMOTION_VOICE_MAP.get(emotion_label, TTS_DEFAULT_VOICE)

        logger.info(
            f"TTS 合成 | text='{text[:20]}...' | "
            f"speed={speed} pitch={pitch} style={style} voice={voice}"
        )

        self.is_playing = True
        try:
            sentences = self._split_sentences(text)
            for sentence in sentences:
                if sentence.strip():
                    yield from self._call_api(sentence, speed, pitch, style, voice)
        except Exception as e:
            logger.error(f"TTS 合成失败: {e}", exc_info=True)
            raise
        finally:
            # 无论成功还是异常，确保状态复位
            self.is_playing = False
            logger.debug("TTS 合成完毕，is_playing = False")


    # ── 非流式合成（测试 / 预合成用）────────────────────────────────────────

    def synthesize_full(
        self,
        text:          str,
        speed:         float = 1.0,
        pitch:         int   = 0,
        style:         str   = 'neutral',
        emotion_label: str   = 'neutral',
    ) -> bytes:
        """非流式合成，返回完整 PCM 字节串。用于测试或短文本预合成。"""
        chunks = list(self.synthesize_stream(text, speed, pitch, style, emotion_label))
        return b''.join(chunks)


    # ── 内部方法 ─────────────────────────────────────────────────────────────

    def _call_api(
        self,
        text:  str,
        speed: float,
        pitch: int,
        style: str,
        voice: str,
    ) -> Generator[bytes, None, None]:
        """
        调用 CosyVoice API 流式合成单个句子。
        每次调用对应一个完整语义单元（句子），保证语气完整。
        """
        synthesizer = SpeechSynthesizer(
            model       = TTS_MODEL,
            voice       = voice,
            format      = AudioFormat.PCM_24000HZ_MONO_16BIT,
            speech_rate = speed,
            pitch_rate  = pitch,
            emotion     = style,
        )
        for chunk in synthesizer.streaming_call(text):
            if chunk is None:
                continue
            frame = chunk.get_audio_frame()
            if frame:
                yield frame

    def _split_sentences(self, text: str) -> list[str]:
        """
        将文本按句末标点分句，每句保留标点在尾部。
        短文本（≤ TTS_MAX_SENTENCE_LEN）直接作为单句处理。
        末尾无标点的片段追加为最后一句。

        示例：
            '我在这里陪着您。听起来今天很难过。'
            → ['我在这里陪着您。', '听起来今天很难过。']
        """
        if len(text) <= TTS_MAX_SENTENCE_LEN:
            return [text]

        matches = _SENTENCE_SPLIT_RE.findall(text)
        if not matches:
            return [text]

        # 检查是否有末尾未匹配的文本（无标点结尾）
        matched_len = sum(len(m) for m in matches)
        if matched_len < len(text):
            remaining = text[matched_len:].strip()
            if remaining:
                matches.append(remaining)

        return matches
```

---

## 7. 路由层实现

### `routers/stream_tts.py`

```python
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from services.tts_service import TTSService
from config import TTS_SPEED_MIN, TTS_SPEED_MAX, TTS_PITCH_MIN, TTS_PITCH_MAX

logger = logging.getLogger(__name__)
router = APIRouter()

# 服务实例由 main.py 注入
tts_service: TTSService = None


# ─── Schema ──────────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text:          str   = Field(...,             description="待合成文本")
    speed:         float = Field(default=1.0,     description="语速倍率 0.5~2.0")
    pitch:         int   = Field(default=0,       description="音调偏移 -12~12（半音）")
    style:         str   = Field(default='neutral', description="情感风格")
    emotion_label: str   = Field(default='neutral', description="用户情绪标签，用于自动选音色")

    @field_validator('speed')
    @classmethod
    def validate_speed(cls, v: float) -> float:
        if not (TTS_SPEED_MIN <= v <= TTS_SPEED_MAX):
            raise ValueError(f"speed 须在 [{TTS_SPEED_MIN}, {TTS_SPEED_MAX}]")
        return v

    @field_validator('pitch')
    @classmethod
    def validate_pitch(cls, v: int) -> int:
        if not (TTS_PITCH_MIN <= v <= TTS_PITCH_MAX):
            raise ValueError(f"pitch 须在 [{TTS_PITCH_MIN}, {TTS_PITCH_MAX}]")
        return v


# ─── 路由 ────────────────────────────────────────────────────────────────────

@router.post('/tts/stream')
async def tts_stream(req: TTSRequest):
    """
    流式语音合成接口。
    返回 Content-Type: audio/pcm，格式 24kHz 16bit 单声道。

    前端调用时机：
      1. STEP 3 onFirstSentence 回调触发 → POST 首句文本（流水线并行）
      2. STEP 3 onReplyDone 回调触发   → POST 剩余文本（排队播放）
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail='text 不能为空')

    def generate():
        for chunk in tts_service.synthesize_stream(
            text          = req.text,
            speed         = req.speed,
            pitch         = req.pitch,
            style         = req.style,
            emotion_label = req.emotion_label,
        ):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type='audio/pcm',
        headers={
            'X-Sample-Rate':     str(24000),
            'X-Channels':        '1',
            'X-Bit-Depth':       '16',
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',   # 禁止 Nginx 缓冲
        },
    )


@router.get('/tts/status')
async def tts_status():
    """
    查询当前 TTS 播放状态。
    前端可轮询此接口判断是否可以恢复麦克风（回声消除辅助）。
    """
    return {'is_playing': tts_service.is_playing}
```

### 与 `main.py` 的连接方式

```python
# main.py（节选）
import routers.stream_tts as stream_tts_router
from services.tts_service import TTSService

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 其他服务初始化 ...
    tts_svc = TTSService()

    # 注入到路由模块
    stream_tts_router.tts_service = tts_svc

    yield

app.include_router(stream_tts_router.router)   # 挂载到端口 8000
```

---

## 8. 回声消除协议

### 8.1 问题描述

```
❌ 不处理时：

AI 语音 → 扬声器 → 麦克风采集到 AI 声音
                              │
                    STEP 1 识别为「用户输入」
                              │
                    触发新一轮 LLM 回复 → 死循环
```

### 8.2 解决方案：浏览器事件门控

通过浏览器自定义事件在 STEP 1（`useASR`）和 STEP 4（`useTTS`）之间传递播放状态，无需后端参与：

```
TTS 开始播放
     │ window.dispatchEvent('tts-start')
     ▼
useASR.ts 监听到
     │ ttsMuted = true
     ▼
ScriptProcessorNode.onaudioprocess
     │ if (ttsMuted) return   ← 跳过发送，麦克风静音
     ▼
[AI 声音通过扬声器播出，麦克风已屏蔽]
     │
TTS 播放完毕
     │ window.dispatchEvent('tts-end')
     ▼
setTimeout(200ms)
     │ ttsMuted = false       ← 延迟恢复，等待房间混响消散
     ▼
麦克风恢复正常采集
```

> ⚠️ **200ms 延迟恢复至关重要**：房间混响会让声音在 TTS 结束后持续 100~300ms，过早恢复会捕捉到残留回声导致误识别。

### 8.3 门控代码位置

```typescript
// composables/useASR.ts 顶部（模块级，全局生效）
let ttsMuted = false

window.addEventListener('tts-start', () => {
    ttsMuted = true
    console.log('[ASR] 麦克风已静音（TTS 播放中）')
})
window.addEventListener('tts-end', () => {
    setTimeout(() => {
        ttsMuted = false
        console.log('[ASR] 麦克风已恢复')
    }, 200)
})

// ScriptProcessorNode 回调中
processor.onaudioprocess = (e) => {
    if (ttsMuted || ws?.readyState !== WebSocket.OPEN) return
    // ... 正常发送 PCM 帧
}
```

---

## 9. LLM-TTS 流水线并行

### 9.1 设计目标

将用户感知延迟（说完话 → 听到 AI 开口）压缩至 **~1.5s**。

### 9.2 时间分解

```
0ms       VAD 检测到静音，触发 ASR + 情绪并发推理
300ms     ASR 输出转录文本，情绪识别完成（并发，同时完成）
300ms     前端收到 transcript 消息，立即 POST /llm/stream
1100ms    LLM 输出第一个完整句子（检测到句末标点）
1100ms    立即 POST /tts/stream（首句，不等 LLM 全文生成）
1900ms    TTS 首个 PCM 块到达前端
1900ms    WebAudio 开始播放
──────────────────────────────────────
用户感知延迟：约 1.5~2.0s
```

### 9.3 首句触发逻辑

```
STEP 3 SSE delta 流:
  "我" → "在" → "这" → "里" → "陪" → "着" → "您" → "。"
                                                        ↑
                                              sentenceBuffer 检测到句末标点
                                                        │
                                    立即调用 onFirstSentence("我在这里陪着您。", ttsParams)
                                                        │
                                              前端 POST /tts/stream（首句）
                                                        │
                                   LLM 继续生成 "听起来今天…" → "。"
                                                        │
                                    onFirstSentence("听起来今天…。", ttsParams)
                                              前端排队 POST /tts/stream
```

### 9.4 多句排队播放

前端使用播放队列保证多句按顺序无缝拼接：

```typescript
// useTTS.ts 内部播放队列
const playQueue: QueueItem[] = []
let isProcessing = false

async function enqueue(text: string, params: TTSParams, emotionLabel: string) {
    playQueue.push({ text, params, emotionLabel })
    if (!isProcessing) {
        await processQueue()   // 启动队列消费
    }
}

async function processQueue() {
    isProcessing = true
    while (playQueue.length > 0) {
        const item = playQueue.shift()!
        await playOnce(item)   // 等待当前句完全播放完毕
    }
    isProcessing = false
    // 所有句子播放完毕，恢复麦克风
    window.dispatchEvent(new CustomEvent('tts-end'))
}
```

---

## 10. HTTP 接口规范

### POST `/tts/stream`

**请求体：**
```json
{
  "text":          "我在这里陪着您。",
  "speed":         0.85,
  "pitch":         -2,
  "style":         "gentle",
  "emotion_label": "sad"
}
```

**响应头：**
```
Content-Type:     audio/pcm
X-Sample-Rate:    24000
X-Channels:       1
X-Bit-Depth:      16
Cache-Control:    no-cache
X-Accel-Buffering: no
```

**响应体：**
```
[二进制 PCM 流...]
格式：24kHz, 16bit, 单声道, Little-endian
```

**错误响应：**
```json
{ "detail": "text 不能为空" }
```

### GET `/tts/status`

```json
{ "is_playing": false }
```

---

## 11. 前端集成代码

### `composables/useTTS.ts`

```typescript
import { ref } from 'vue'

// ── 类型定义 ─────────────────────────────────────────────────────────────────
interface TTSParams {
  speed: number
  pitch: number
  style: string
}

interface QueueItem {
  text:         string
  params:       TTSParams
  emotionLabel: string
}


// ── Composable ────────────────────────────────────────────────────────────────
export function useTTS(apiBase = 'http://localhost:8000') {
  const isPlaying = ref(false)

  // 播放完毕回调（父组件用于恢复 UI 状态）
  const onPlaybackDone = ref<(() => void) | null>(null)

  // WebAudio 上下文（每次对话新建）
  let audioCtx:      AudioContext | null = null
  let nextStartTime: number        = 0   // 精确调度：下一块音频的开始时间点

  // 播放队列
  const playQueue:    QueueItem[]  = []
  let   isProcessing: boolean      = false


  // ── 公开接口：加入播放队列 ──────────────────────────────────────────────────

  async function speak(
    text:         string,
    params:       TTSParams,
    emotionLabel: string = 'neutral',
  ) {
    if (!text.trim()) return
    playQueue.push({ text, params, emotionLabel })

    // 若队列未在消费，启动消费
    if (!isProcessing) {
      await _processQueue()
    }
  }


  // ── 队列消费 ─────────────────────────────────────────────────────────────

  async function _processQueue() {
    isProcessing    = true
    isPlaying.value = true

    // TTS 开始时通知 STEP 1 暂停麦克风
    window.dispatchEvent(new CustomEvent('tts-start'))

    while (playQueue.length > 0) {
      const item = playQueue.shift()!
      await _playOnce(item)
    }

    isProcessing    = false
    isPlaying.value = false

    // TTS 全部播放完毕，通知 STEP 1 恢复麦克风
    window.dispatchEvent(new CustomEvent('tts-end'))
    onPlaybackDone.value?.()
  }


  // ── 单句播放 ─────────────────────────────────────────────────────────────

  async function _playOnce(item: QueueItem): Promise<void> {
    // 初始化 AudioContext（首次或已关闭时新建）
    if (!audioCtx || audioCtx.state === 'closed') {
      audioCtx      = new AudioContext({ sampleRate: 24000 })
      nextStartTime = audioCtx.currentTime
    }

    try {
      const res = await fetch(`${apiBase}/tts/stream`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          text:          item.text,
          speed:         item.params.speed,
          pitch:         item.params.pitch,
          style:         item.params.style,
          emotion_label: item.emotionLabel,
        }),
      })

      if (!res.ok || !res.body) {
        console.error(`[TTS] 请求失败: HTTP ${res.status}`)
        return
      }

      const reader = res.body.getReader()

      // PCM 帧大小：100ms @ 24kHz 16bit = 4800 bytes
      const FRAME_BYTES = 4800
      let   pcmBuffer   = new Uint8Array(0)

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        // 追加新数据到缓冲区
        const merged = new Uint8Array(pcmBuffer.length + value.length)
        merged.set(pcmBuffer)
        merged.set(value, pcmBuffer.length)
        pcmBuffer = merged

        // 按帧调度播放（收到足够数据立即播放，不等全部下载完）
        while (pcmBuffer.length >= FRAME_BYTES) {
          _scheduleFrame(pcmBuffer.slice(0, FRAME_BYTES))
          pcmBuffer = pcmBuffer.slice(FRAME_BYTES)
        }
      }

      // 播放剩余不足一帧的数据
      if (pcmBuffer.length > 0) {
        _scheduleFrame(pcmBuffer)
      }

      // 等待已调度音频全部播放完毕，再处理下一句
      const remainingMs = Math.max(
        0,
        (nextStartTime - audioCtx.currentTime + 0.1) * 1000,
      )
      await _sleep(remainingMs)

    } catch (err) {
      console.error('[TTS] 播放异常:', err)
    }
  }


  // ── PCM 帧精确调度（WebAudio 时钟，无缝拼接）─────────────────────────────

  function _scheduleFrame(pcmData: Uint8Array): void {
    if (!audioCtx) return

    // Int16 PCM → Float32（WebAudio 需要 Float32）
    const int16   = new Int16Array(pcmData.buffer, pcmData.byteOffset, pcmData.byteLength / 2)
    const float32 = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768.0
    }

    const audioBuffer = audioCtx.createBuffer(1, float32.length, 24000)
    audioBuffer.copyToChannel(float32, 0)

    const source = audioCtx.createBufferSource()
    source.buffer = audioBuffer
    source.connect(audioCtx.destination)

    // 精确调度：在上一帧结束时刻开始，保证无缝拼接
    const startAt   = Math.max(audioCtx.currentTime, nextStartTime)
    source.start(startAt)
    nextStartTime = startAt + audioBuffer.duration
  }


  // ── 强制停止 ─────────────────────────────────────────────────────────────

  function stop(): void {
    // 清空队列
    playQueue.length = 0
    isProcessing     = false
    isPlaying.value  = false

    // 关闭 AudioContext（立即中断播放）
    audioCtx?.close()
    audioCtx      = null
    nextStartTime = 0

    window.dispatchEvent(new CustomEvent('tts-end'))
  }


  // ── 工具 ─────────────────────────────────────────────────────────────────

  function _sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms))
  }

  return { isPlaying, onPlaybackDone, speak, stop }
}
```

---

## 12. 全链路时序图

```
用户        STEP1(ASR)      STEP2(情绪)    STEP3(LLM)      STEP4(TTS)
 │              │                │               │               │
 │── 说话 ─────▶│                │               │               │
 │              │ 累积 PCM 帧    │               │               │
 │── 停止 ─────▶│                │               │               │
 │           (0ms)               │               │               │
 │              │─ gather ───────▶│               │               │
 │              │  ASR 推理       │ 情绪推理       │               │
 │           (300ms)              │               │               │
 │              │◀─ transcript + emotion ─────────│               │
 │              │                │               │               │
 │              │ WebSocket 推送  │               │               │
 │              │─────────────────────────────────────────────────│
 │              │                │   POST /llm/stream             │
 │              │                │──────────────▶│               │
 │           (1100ms)            │               │ 首句生成        │
 │              │                │               │── POST /tts/stream ─▶│
 │              │                │               │ 继续生成        │ 合成首句
 │           (1900ms)            │               │               │
 │◀── 听到 AI 开口 ────────────────────────────────────────────────│
 │              │                │               │ done 事件      │
 │              │                │               │── 剩余句 ──────▶│ 排队合成
 │◀── AI 继续说话 ─────────────────────────────────────────────────│
 │              │                │               │            播放完毕
 │              │                │               │               │─ tts-end
 │              │ ttsMuted=false  │               │               │
 │── 继续说话 ──▶│                │               │               │
```

---

## 13. TDD 验收测试

### `tests/test_tts_service.py`

```python
import pytest
import numpy as np
from unittest.mock import patch, MagicMock, call
from config import (
    TTS_SPEED_MIN, TTS_SPEED_MAX,
    TTS_PITCH_MIN, TTS_PITCH_MAX,
    TTS_STYLE_MAP, TTS_EMOTION_VOICE_MAP,
    TTS_MAX_SENTENCE_LEN,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    """每个测试用例使用独立 TTSService 实例。"""
    from services.tts_service import TTSService
    return TTSService()


def make_pcm(duration_ms: int = 100, sample_rate: int = 24000) -> bytes:
    """生成测试用静音 PCM 数据块。"""
    samples = int(sample_rate * duration_ms / 1000)
    return np.zeros(samples, dtype=np.int16).tobytes()


# ─── TC-01: 空文本处理 ───────────────────────────────────────────────────────

class TestEmptyText:

    def test_empty_string_yields_nothing(self, svc):
        """TC-01: 空字符串不调用 API，不产生任何输出"""
        with patch.object(svc, '_call_api') as mock_api:
            result = list(svc.synthesize_stream(''))
            mock_api.assert_not_called()
            assert result == []

    def test_whitespace_only_yields_nothing(self, svc):
        """TC-02: 纯空白字符串不产生输出"""
        with patch.object(svc, '_call_api') as mock_api:
            list(svc.synthesize_stream('   \n  '))
            mock_api.assert_not_called()

    def test_empty_text_http_400(self):
        """TC-03: POST /tts/stream 空 text 返回 400"""
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        res = client.post('/tts/stream', json={
            'text': '', 'speed': 1.0, 'pitch': 0,
            'style': 'neutral', 'emotion_label': 'neutral',
        })
        assert res.status_code == 400


# ─── TC-02: 参数校验与裁剪 ───────────────────────────────────────────────────

class TestParameterValidation:

    def _capture_call_params(self, svc, **kwargs):
        """辅助方法：调用合成并捕获传给 _call_api 的参数。"""
        captured = {}
        def mock_call(text, speed, pitch, style, voice):
            captured.update({'speed': speed, 'pitch': pitch,
                             'style': style, 'voice': voice})
            return iter([])
        with patch.object(svc, '_call_api', side_effect=mock_call):
            list(svc.synthesize_stream('测试', **kwargs))
        return captured

    def test_speed_below_min_clamped(self, svc):
        """TC-04: 语速低于 SPEED_MIN 时被裁剪到下限"""
        params = self._capture_call_params(svc, speed=0.1)
        assert params['speed'] == TTS_SPEED_MIN

    def test_speed_above_max_clamped(self, svc):
        """TC-05: 语速高于 SPEED_MAX 时被裁剪到上限"""
        params = self._capture_call_params(svc, speed=99.0)
        assert params['speed'] == TTS_SPEED_MAX

    def test_pitch_below_min_clamped(self, svc):
        """TC-06: 音调低于 PITCH_MIN 时被裁剪到下限"""
        params = self._capture_call_params(svc, pitch=-99)
        assert params['pitch'] == TTS_PITCH_MIN

    def test_pitch_above_max_clamped(self, svc):
        """TC-07: 音调高于 PITCH_MAX 时被裁剪到上限"""
        params = self._capture_call_params(svc, pitch=99)
        assert params['pitch'] == TTS_PITCH_MAX

    def test_unknown_style_falls_back_to_neutral(self, svc):
        """TC-08: 未知风格标签回退为 neutral"""
        params = self._capture_call_params(svc, style='unknown_style')
        assert params['style'] == 'neutral'

    def test_happy_emotion_uses_lively_voice(self, svc):
        """TC-09: happy 情绪自动选择活泼音色"""
        params = self._capture_call_params(svc, emotion_label='happy')
        assert params['voice'] == TTS_EMOTION_VOICE_MAP['happy']

    def test_all_emotions_have_voice_mapping(self):
        """TC-10: 所有情绪标签（含 _crisis）均有音色映射"""
        labels = ['neutral', 'happy', 'sad', 'angry',
                  'fearful', 'disgusted', 'surprised', '_crisis']
        for label in labels:
            assert label in TTS_EMOTION_VOICE_MAP, f"缺少音色映射: {label}"

    def test_all_styles_in_style_map(self):
        """TC-11: 所有风格标签均在映射表中"""
        for style in ['gentle', 'calm', 'cheerful', 'neutral']:
            assert style in TTS_STYLE_MAP


# ─── TC-03: is_playing 状态管理 ──────────────────────────────────────────────

class TestPlayingState:

    def test_is_playing_true_during_synthesis(self, svc):
        """TC-12: 合成过程中 is_playing 为 True"""
        states = []
        def mock_call(text, speed, pitch, style, voice):
            states.append(svc.is_playing)
            yield make_pcm()
        with patch.object(svc, '_call_api', side_effect=mock_call):
            list(svc.synthesize_stream('测试'))
        assert True in states

    def test_is_playing_false_after_success(self, svc):
        """TC-13: 合成完成后 is_playing 复位为 False"""
        with patch.object(svc, '_call_api', return_value=iter([make_pcm()])):
            list(svc.synthesize_stream('测试'))
        assert svc.is_playing is False

    def test_is_playing_false_after_exception(self, svc):
        """TC-14: 合成抛出异常后 is_playing 仍然复位（finally 保证）"""
        with patch.object(svc, '_call_api', side_effect=RuntimeError("API 错误")):
            with pytest.raises(RuntimeError):
                list(svc.synthesize_stream('测试'))
        assert svc.is_playing is False


# ─── TC-04: 分句逻辑 ─────────────────────────────────────────────────────────

class TestSentenceSplitting:

    def test_short_text_not_split(self, svc):
        """TC-15: 短文本（≤ MAX_SENTENCE_LEN）不分句"""
        text = '我在这里陪着您。'
        assert len(text) <= TTS_MAX_SENTENCE_LEN
        assert svc._split_sentences(text) == [text]

    def test_three_sentences_split_correctly(self, svc):
        """TC-16: 三句话按标点正确分句"""
        text      = '我在这里陪着您。听起来今天很难过。能跟我说说吗？'
        sentences = svc._split_sentences(text)
        assert len(sentences) == 3
        assert sentences[0] == '我在这里陪着您。'
        assert sentences[1] == '听起来今天很难过。'
        assert sentences[2] == '能跟我说说吗？'

    def test_text_without_punctuation_single_sentence(self, svc):
        """TC-17: 无标点文本作为单句返回"""
        text = '没有任何标点的一段话'
        assert svc._split_sentences(text) == [text]

    def test_trailing_text_without_punctuation_captured(self, svc):
        """TC-18: 末尾无标点的文本被追加为最后一句"""
        text      = '第一句话。第二句话'
        sentences = svc._split_sentences(text)
        assert len(sentences) == 2
        assert sentences[-1] == '第二句话'

    def test_long_text_triggers_split(self, svc):
        """TC-19: 超过 MAX_SENTENCE_LEN 的文本触发分句处理"""
        long_text = '这是第一句，有完整的标点。' + '这是第二句话，也有标点。' * 3
        assert len(long_text) > TTS_MAX_SENTENCE_LEN
        sentences = svc._split_sentences(long_text)
        assert len(sentences) > 1

    def test_each_sentence_called_separately(self, svc):
        """TC-20: 多句文本中每个句子独立调用一次 _call_api"""
        text = '第一句。第二句！第三句？'
        call_count = []
        def mock_call(t, speed, pitch, style, voice):
            call_count.append(t)
            return iter([make_pcm()])
        with patch.object(svc, '_call_api', side_effect=mock_call):
            list(svc.synthesize_stream(text))
        assert len(call_count) == 3


# ─── TC-05: 输出格式 ─────────────────────────────────────────────────────────

class TestOutputFormat:

    def test_synthesize_stream_yields_bytes(self, svc):
        """TC-21: synthesize_stream 产出 bytes 类型数据"""
        pcm = make_pcm()
        with patch.object(svc, '_call_api', return_value=iter([pcm])):
            chunks = list(svc.synthesize_stream('测试'))
        assert all(isinstance(c, bytes) for c in chunks)

    def test_synthesize_full_returns_bytes(self, svc):
        """TC-22: synthesize_full 返回 bytes 类型"""
        pcm = make_pcm()
        with patch.object(svc, '_call_api', return_value=iter([pcm])):
            result = svc.synthesize_full('测试')
        assert isinstance(result, bytes)

    def test_synthesize_full_concatenates_chunks(self, svc):
        """TC-23: synthesize_full 正确拼接多个 PCM 块"""
        chunk1 = make_pcm(100)
        chunk2 = make_pcm(200)
        with patch.object(svc, '_call_api', return_value=iter([chunk1, chunk2])):
            result = svc.synthesize_full('测试')
        assert len(result) == len(chunk1) + len(chunk2)

    def test_none_chunk_skipped(self, svc):
        """TC-24: _call_api 返回 None 块时不产生输出（API 心跳包）"""
        pcm = make_pcm()
        def mock_api(text, speed, pitch, style, voice):
            mock_chunk_none = MagicMock()
            mock_chunk_none.get_audio_frame.return_value = None
            mock_chunk_valid = MagicMock()
            mock_chunk_valid.get_audio_frame.return_value = pcm
            yield mock_chunk_none
            yield mock_chunk_valid
        with patch('services.tts_service.SpeechSynthesizer') as mock_synth:
            mock_synth.return_value.streaming_call.side_effect = \
                lambda t: mock_api(t, None, None, None, None)
            chunks = list(svc._call_api('测试', 1.0, 0, 'neutral', 'longxiaochun'))
        assert chunks == [pcm]


# ─── TC-06: FastAPI 路由层 ───────────────────────────────────────────────────

class TestRouterLayer:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def test_stream_endpoint_returns_audio_pcm(self, client):
        """TC-25: POST /tts/stream 返回 Content-Type: audio/pcm"""
        pcm = make_pcm()
        with patch('routers.stream_tts.tts_service') as mock_svc:
            mock_svc.synthesize_stream.return_value = iter([pcm])
            res = client.post('/tts/stream', json={
                'text':          '测试文本',
                'speed':         1.0,
                'pitch':         0,
                'style':         'neutral',
                'emotion_label': 'neutral',
            })
        assert res.status_code == 200
        assert 'audio/pcm' in res.headers.get('content-type', '')

    def test_stream_endpoint_rejects_empty_text(self, client):
        """TC-26: POST /tts/stream 空 text 返回 400"""
        res = client.post('/tts/stream', json={
            'text': '', 'speed': 1.0, 'pitch': 0,
            'style': 'neutral', 'emotion_label': 'neutral',
        })
        assert res.status_code == 400

    def test_stream_endpoint_rejects_invalid_speed(self, client):
        """TC-27: POST /tts/stream 非法 speed 返回 422"""
        res = client.post('/tts/stream', json={
            'text': '测试', 'speed': 99.0, 'pitch': 0,
            'style': 'neutral', 'emotion_label': 'neutral',
        })
        assert res.status_code == 422

    def test_status_endpoint_returns_is_playing(self, client):
        """TC-28: GET /tts/status 返回 is_playing 字段"""
        res = client.get('/tts/status')
        assert res.status_code == 200
        assert 'is_playing' in res.json()

    def test_response_headers_include_sample_rate(self, client):
        """TC-29: 响应头包含 X-Sample-Rate"""
        pcm = make_pcm()
        with patch('routers.stream_tts.tts_service') as mock_svc:
            mock_svc.synthesize_stream.return_value = iter([pcm])
            res = client.post('/tts/stream', json={
                'text': '测试', 'speed': 1.0, 'pitch': 0,
                'style': 'neutral', 'emotion_label': 'neutral',
            })
        assert res.headers.get('x-sample-rate') == '24000'
```

### 验收标准汇总

| ID | 分类 | 描述 | 通过条件 |
|----|------|------|----------|
| TC-01 | 空文本 | 空字符串不调 API | mock 未被调用，输出 [] |
| TC-02 | 空文本 | 纯空白不输出 | 同上 |
| TC-03 | 空文本 | HTTP 400 | status_code == 400 |
| TC-04 | 参数 | 语速下限裁剪 | speed == SPEED_MIN |
| TC-05 | 参数 | 语速上限裁剪 | speed == SPEED_MAX |
| TC-06 | 参数 | 音调下限裁剪 | pitch == PITCH_MIN |
| TC-07 | 参数 | 音调上限裁剪 | pitch == PITCH_MAX |
| TC-08 | 参数 | 未知风格回退 | style == neutral |
| TC-09 | 参数 | happy 音色 | voice == 映射值 |
| TC-10 | 参数 | 8 种情绪有音色 | 所有 label 均存在 |
| TC-11 | 参数 | 4 种风格在表中 | 所有 style 均存在 |
| TC-12 | 状态 | 合成中为 True | states 含 True |
| TC-13 | 状态 | 完成后复位 | is_playing == False |
| TC-14 | 状态 | 异常后复位 | finally 保证 |
| TC-15 | 分句 | 短文本不分句 | sentences 长度 == 1 |
| TC-16 | 分句 | 三句正确切分 | 长度 == 3，内容正确 |
| TC-17 | 分句 | 无标点单句 | 长度 == 1 |
| TC-18 | 分句 | 末尾无标点追加 | 末句内容正确 |
| TC-19 | 分句 | 长文本触发分句 | 长度 > 1 |
| TC-20 | 分句 | 每句独立调用 | call_count == 3 |
| TC-21 | 格式 | stream 产出 bytes | 类型验证通过 |
| TC-22 | 格式 | full 返回 bytes | 类型验证通过 |
| TC-23 | 格式 | full 正确拼接 | 长度 == 两块之和 |
| TC-24 | 格式 | None 块被跳过 | 输出只含有效块 |
| TC-25 | 路由 | 返回 audio/pcm | content-type 正确 |
| TC-26 | 路由 | 空 text 返回 400 | status_code == 400 |
| TC-27 | 路由 | 非法 speed 422 | status_code == 422 |
| TC-28 | 路由 | status 字段存在 | is_playing 存在 |
| TC-29 | 路由 | 响应头含采样率 | X-Sample-Rate == 24000 |

---

## 附录：四步服务端口汇总（合并架构）

| 接口 | 路径 | 协议 | 说明 |
|------|------|------|------|
| ASR 实时转录 + 情绪 | `ws://host:8000/ws/asr` | WebSocket | STEP 1 + STEP 2 并发，一条消息返回 |
| LLM 流式回复 | `POST :8000/llm/stream` | HTTP SSE | STEP 3 |
| LLM 重置 | `POST :8000/llm/reset` | HTTP | STEP 3 |
| TTS 流式合成 | `POST :8000/tts/stream` | HTTP 流式 | STEP 4 |
| TTS 状态查询 | `GET  :8000/tts/status` | HTTP | STEP 4 |
| 会话全局重置 | `POST :8000/session/reset` | HTTP | 同时重置 STEP 2、3 |
| 健康检查 | `GET  :8000/health` | HTTP | 全局 |
