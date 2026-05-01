# STEP 4 — 情绪语音合成模块
**技术栈：通义千问 CosyVoice TTS API + WebAudio API 流式播放**

---

## 目录
1. [模块概述](#1-模块概述)
2. [治愈性对称原则](#2-治愈性对称原则)
3. [系统架构](#3-系统架构)
4. [API 选型与音色设计](#4-api-选型与音色设计)
5. [环境依赖与配置](#5-环境依赖与配置)
6. [核心实现代码](#6-核心实现代码)
7. [回声消除协议](#7-回声消除协议)
8. [LLM-TTS 流水线并行](#8-llm-tts-流水线并行)
9. [HTTP 接口规范](#9-http-接口规范)
10. [前端集成代码](#10-前端集成代码)
11. [全链路时序图](#11-全链路时序图)
12. [TDD 验收测试](#12-tdd-验收测试)

---

## 1. 模块概述

本模块接收 **STEP 3 输出的回复文本**与 **TTS 情绪参数**，调用**通义千问 CosyVoice TTS API** 生成带有情绪色彩的语音，通过流式 PCM 传输实现低延迟播放。

同时处理两个关键工程问题：
- **回声消除**：TTS 播放期间暂停麦克风发送，防止 AI 声音被 STEP 1 误识别为用户输入
- **流水线并行**：与 STEP 3 LLM 生成并行，STEP 3 输出第一个完整句子时立即开始合成，不等全文生成完毕

### 目标指标

| 指标 | 目标值 |
|------|--------|
| 首句播放延迟 | STEP 3 推送首句后 ≤ 800ms 开始发声 |
| 音频格式 | PCM 24kHz 16bit 单声道 |
| 情绪覆盖 | 7 种情绪对应不同语速、音调、风格 |
| 回声隔离 | TTS 播放期间 ASR 帧发送暂停，恢复延迟 200ms |
| 播放连续性 | 多句流式拼接无明显卡顿 |

### 与其他模块的关系

```
STEP 3 ──→ tts_params + 回复文本
                │
        ┌───────┴───────┐
        ▼               ▼
   后端 TTS 合成    前端 WebAudio 播放
  (CosyVoice API)  (PCM 流式解码)
        │               │
        └───────┬───────┘
                ▼
        播放完毕事件
                │
        通知 STEP 1 恢复麦克风
```

---

## 2. 治愈性对称原则

> **核心设计原则：TTS 情绪不应镜像用户情绪，而应是治愈性的对立平衡。**

用户悲伤时，AI 用温柔平静的声音陪伴；用户愤怒时，AI 用更慢更温和的语调进行情绪降温。TTS 的声音本身就是治疗手段，而非情绪的反射。

### 情绪 → TTS 参数映射

| 用户情绪 | TTS 目标情绪 | 语速 | 音调 | 风格 | 设计理由 |
|----------|------------|------|------|------|----------|
| `sad` 悲伤 | 温柔陪伴 | 0.85 | -2 | gentle | 慢速低调传递陪伴感，不急于改变情绪 |
| `fearful` 焦虑 | 平静稳定 | 0.88 | -1 | calm | 用平静语调引导降低焦虑 |
| `angry` 愤怒 | 温和降温 | 0.88 | -1 | gentle | 绝对不能也用激动语气，平和降温 |
| `happy` 快乐 | 轻松愉悦 | 1.05 | +1 | cheerful | 与用户共鸣，强化积极情绪 |
| `disgusted` 厌恶 | 温和理解 | 0.92 | -1 | calm | 平和接纳，不对立 |
| `surprised` 惊讶 | 稳定中性 | 1.00 | 0 | neutral | 先稳定，观察正负性再调整 |
| `neutral` 平静 | 自然亲切 | 1.00 | 0 | neutral | 维持自然对话节奏 |
| `_crisis` 危机 | 极度温柔 | 0.82 | -2 | gentle | 最平缓语调，传递安全感 |

> **参数说明：**
> - `speed`：语速倍率，1.0 为正常，<1.0 偏慢，>1.0 偏快
> - `pitch`：音调偏移（半音），负值降调，正值升调
> - `style`：CosyVoice 情感风格标签

---

## 3. 系统架构

### 3.1 数据流

```
STEP 3 onFirstSentence 回调
  { text: "第一句话。", tts_params: { speed, pitch, style } }
          │
          ▼
POST /tts/stream
          │
          ▼
TTSService.synthesize_stream(text, speed, pitch, style)
  │
  ├─ 1. 参数校验与边界处理
  │      ├─ text 为空 → 直接返回，不调用 API
  │      ├─ text 过长（>200字）→ 分句合成
  │      └─ speed/pitch 范围校验
  │
  ├─ 2. 调用 CosyVoice API（流式）
  │      └─ 返回 PCM 音频块流
  │
  ├─ 3. 流式推送 PCM 数据
  │      └─ StreamingResponse(media_type='audio/pcm')
  │
  ▼
前端 useTTS.ts
  │
  ├─ 4. 接收 PCM 流
  │      ├─ 分块解码 Int16 → Float32
  │      └─ 维护 nextStartTime 实现无缝拼接
  │
  ├─ 5. WebAudio API 流式播放
  │      ├─ createBufferSource 逐块播放
  │      └─ 精确调度保证播放连续无卡顿
  │
  └─ 6. 播放完毕
         ├─ isPlaying = false
         ├─ 发出 tts-end 事件（通知 STEP 1 恢复麦克风）
         └─ 触发 onPlaybackDone 回调
```

### 3.2 多句流水线架构

```
STEP 3 LLM 流式输出:

  chunk: "我"+"在"+"这"+"里"+"陪"+"着"+"您"+"。"  ← 第1句检测到
                                              │
                                    立即发起 TTS 请求①
                                              │
  chunk: "听"+"起"+"来"+"今"+"天"+"心"+"里"+"很"+"沉"+"，"
  chunk: "很"+"想"+"念"+"他"+"。"  ← 第2句检测到
                        │
              TTS 请求① 播放中
              立即发起 TTS 请求②（排队）
                        │
  done 事件到来        ↓
              TTS 请求① 播放完毕 → 立即开始 TTS 请求②
```

---

## 4. API 选型与音色设计

### 4.1 API 选型

| 方案 | 延迟 | 情绪控制 | CPU/GPU | 推荐度 |
|------|------|---------|---------|--------|
| **通义千问 CosyVoice API（云端）** | 低，流式 | 支持情感风格 | 无需本地资源 | ⭐⭐⭐⭐⭐ 推荐 |
| CosyVoice 2 本地部署 | 中 | 完整支持 | 需要 GPU | ❌ 无 GPU 不可用 |
| 通义千问标准 TTS | 低，流式 | 有限 | 无需本地 | ⭐⭐⭐ |

> ✅ **无 GPU 环境首选**：`cosyvoice-v1` 云端 API，支持情感风格控制（gentle/calm/cheerful/neutral），流式 PCM 输出，单字符成本低。

### 4.2 推荐音色

| 音色 ID | 名称 | 特点 | 推荐场景 |
|---------|------|------|----------|
| `longxiaochun` | 龙小淳 | 温柔女声，亲切自然 | **默认推荐**，老年陪伴 |
| `longxiaoxia` | 龙小夏 | 活泼女声，语调轻快 | 用户情绪积极时切换 |
| `longshuo` | 龙硕 | 沉稳男声，充满信赖感 | 用户需要权威感/安全感时 |
| `longshu` | 龙书 | 标准中性，清晰 | 功能性播报场景 |

> 💡 音色可在配置文件中设置默认值，也支持按情绪动态切换（如 `happy` → `longxiaoxia`，`sad` → `longxiaochun`）。

---

## 5. 环境依赖与配置

### 5.1 安装依赖

```
# requirements_step4.txt
dashscope>=1.17.0         # 通义千问 SDK（含 TTS）
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
pydantic>=2.0.0
python-dotenv>=1.0.0
```

```bash
pip install -r requirements_step4.txt
```

### 5.2 环境变量 `.env`

```
# 通义千问 API Key（与 STEP 3 共用）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

# TTS 默认配置
TTS_DEFAULT_VOICE=longxiaochun
TTS_DEFAULT_SPEED=1.0
TTS_DEFAULT_STYLE=neutral

# 服务端口
TTS_PORT=8003
```

### 5.3 目录结构

```
step4_tts/
├── tts_service.py         # 核心 TTS 合成服务
├── tts_server.py          # FastAPI 流式服务
├── config.py              # 配置常量
├── .env
└── tests/
    └── test_step4.py
```

---

## 6. 核心实现代码

### 6.1 配置文件 `config.py`

```python
import os
from dotenv import load_dotenv

load_dotenv()

# API 配置
DASHSCOPE_API_KEY = os.environ['DASHSCOPE_API_KEY']

# 模型与音色
TTS_MODEL         = 'cosyvoice-v1'
DEFAULT_VOICE     = os.getenv('TTS_DEFAULT_VOICE', 'longxiaochun')
DEFAULT_SPEED     = float(os.getenv('TTS_DEFAULT_SPEED', '1.0'))
DEFAULT_STYLE     = os.getenv('TTS_DEFAULT_STYLE', 'neutral')

# 音频格式
SAMPLE_RATE       = 24000   # CosyVoice 输出 24kHz
CHANNELS          = 1       # 单声道
BIT_DEPTH         = 16      # 16bit PCM

# 参数范围限制（防止越界导致 API 错误）
SPEED_MIN, SPEED_MAX = 0.5, 2.0
PITCH_MIN, PITCH_MAX = -12, 12

# 情绪风格 → CosyVoice 风格标签映射
STYLE_MAP = {
    'gentle':   'gentle',
    'calm':     'calm',
    'cheerful': 'cheerful',
    'neutral':  'neutral',
}

# 情绪 → 音色映射（可选，默认全部使用 DEFAULT_VOICE）
EMOTION_VOICE_MAP = {
    'happy':   'longxiaoxia',    # 活泼音色匹配快乐情绪
    'neutral': 'longxiaochun',
    'sad':     'longxiaochun',
    'fearful': 'longxiaochun',
    'angry':   'longxiaochun',
    'disgusted':'longxiaochun',
    'surprised':'longxiaochun',
    '_crisis': 'longxiaochun',
}

# 分句合成阈值（超过此长度按标点分句分批合成）
MAX_SINGLE_SENTENCE_LEN = 200
```

### 6.2 核心服务 `tts_service.py`

```python
import re
import logging
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat
from typing import Generator
from config import (
    DASHSCOPE_API_KEY, TTS_MODEL, DEFAULT_VOICE,
    DEFAULT_SPEED, DEFAULT_STYLE, SAMPLE_RATE,
    SPEED_MIN, SPEED_MAX, PITCH_MIN, PITCH_MAX,
    STYLE_MAP, EMOTION_VOICE_MAP, MAX_SINGLE_SENTENCE_LEN,
)

logger = logging.getLogger(__name__)
dashscope.api_key = DASHSCOPE_API_KEY

# 分句正则：在句末标点处切分
SENTENCE_SPLIT_RE = re.compile(r'([^。！？.!?]+[。！？.!?])')


class TTSService:

    def __init__(self):
        # 播放状态标志：True 表示正在播放，STEP 1 据此暂停麦克风
        self.is_playing: bool = False
        logger.info("TTS 服务初始化完成 ✅")


    # ── 主入口：流式合成 ──────────────────────────────────────────────────────

    def synthesize_stream(
        self,
        text:     str,
        speed:    float = DEFAULT_SPEED,
        pitch:    int   = 0,
        style:    str   = DEFAULT_STYLE,
        voice:    str   = DEFAULT_VOICE,
        emotion_label: str = 'neutral',
    ) -> Generator[bytes, None, None]:
        """
        流式语音合成，yield PCM 音频块（bytes）。
        音频格式：PCM 24kHz 16bit 单声道

        Args:
            text:          待合成文本
            speed:         语速倍率（0.5~2.0）
            pitch:         音调偏移，半音（-12~12）
            style:         情感风格（gentle/calm/cheerful/neutral）
            voice:         音色 ID
            emotion_label: 用于按情绪自动选择音色（覆盖 voice 参数）
        """
        if not text or not text.strip():
            logger.debug("文本为空，跳过 TTS 合成")
            return

        # 参数范围校验与裁剪
        speed = max(SPEED_MIN, min(SPEED_MAX, speed))
        pitch = max(PITCH_MIN, min(PITCH_MAX, int(pitch)))
        style = STYLE_MAP.get(style, 'neutral')

        # 按情绪选择音色（若有映射则覆盖传入的 voice）
        voice = EMOTION_VOICE_MAP.get(emotion_label, voice)

        logger.info(
            f"TTS 合成 | 文本={text[:30]}... | "
            f"speed={speed} pitch={pitch} style={style} voice={voice}"
        )

        self.is_playing = True
        try:
            # 长文本分句合成，保证每句自然停顿
            if len(text) > MAX_SINGLE_SENTENCE_LEN:
                sentences = self._split_sentences(text)
                for sentence in sentences:
                    if sentence.strip():
                        yield from self._call_api(sentence, speed, pitch, style, voice)
            else:
                yield from self._call_api(text, speed, pitch, style, voice)
        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")
            raise
        finally:
            self.is_playing = False
            logger.debug("TTS 合成完成，is_playing = False")


    # ── 非流式合成（用于预合成或测试）────────────────────────────────────────

    def synthesize_full(
        self,
        text:     str,
        speed:    float = DEFAULT_SPEED,
        pitch:    int   = 0,
        style:    str   = DEFAULT_STYLE,
        voice:    str   = DEFAULT_VOICE,
        emotion_label: str = 'neutral',
    ) -> bytes:
        """非流式合成，返回完整 PCM 字节串。"""
        chunks = list(self.synthesize_stream(text, speed, pitch, style, voice, emotion_label))
        return b''.join(chunks)


    # ── 内部方法 ─────────────────────────────────────────────────────────────

    def _call_api(
        self, text: str, speed: float, pitch: int, style: str, voice: str
    ) -> Generator[bytes, None, None]:
        """调用 CosyVoice API，yield 原始 PCM 块。"""
        synthesizer = SpeechSynthesizer(
            model       = TTS_MODEL,
            voice       = voice,
            format      = AudioFormat.PCM_24000HZ_MONO_16BIT,
            speech_rate = speed,
            pitch_rate  = pitch,
            emotion     = style,
        )

        for audio_chunk in synthesizer.streaming_call(text):
            if audio_chunk is None:
                continue
            frame = audio_chunk.get_audio_frame()
            if frame:
                yield frame


    def _split_sentences(self, text: str) -> list[str]:
        """
        按中文句末标点分句，返回句子列表。
        保留标点在句尾，保证语气完整。
        """
        matches = SENTENCE_SPLIT_RE.findall(text)
        if not matches:
            return [text]

        # 检查是否有尾部未匹配的文本（末句无标点）
        matched_len = sum(len(m) for m in matches)
        if matched_len < len(text):
            remaining = text[matched_len:].strip()
            if remaining:
                matches.append(remaining)

        return matches
```

### 6.3 FastAPI 服务 `tts_server.py`

```python
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from tts_service import TTSService
from config import SPEED_MIN, SPEED_MAX, PITCH_MIN, PITCH_MAX

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="TTS Service - STEP 4")
tts = TTSService()


# ─── Schema ──────────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text:          str   = Field(..., description="待合成文本")
    speed:         float = Field(default=1.0,  description="语速倍率 0.5~2.0")
    pitch:         int   = Field(default=0,    description="音调偏移 -12~12（半音）")
    style:         str   = Field(default='neutral', description="情感风格")
    voice:         str   = Field(default='longxiaochun', description="音色 ID")
    emotion_label: str   = Field(default='neutral', description="用户情绪标签，用于自动选音色")

    @field_validator('speed')
    @classmethod
    def validate_speed(cls, v):
        if not (SPEED_MIN <= v <= SPEED_MAX):
            raise ValueError(f"speed 必须在 [{SPEED_MIN}, {SPEED_MAX}] 范围内")
        return v

    @field_validator('pitch')
    @classmethod
    def validate_pitch(cls, v):
        if not (PITCH_MIN <= v <= PITCH_MAX):
            raise ValueError(f"pitch 必须在 [{PITCH_MIN}, {PITCH_MAX}] 范围内")
        return v


# ─── 路由 ────────────────────────────────────────────────────────────────────

@app.post('/tts/stream')
async def tts_stream(req: TTSRequest):
    """
    流式语音合成接口。
    返回 Content-Type: audio/pcm，格式 24kHz 16bit 单声道 PCM。
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text 不能为空")

    def generate():
        for chunk in tts.synthesize_stream(
            text          = req.text,
            speed         = req.speed,
            pitch         = req.pitch,
            style         = req.style,
            voice         = req.voice,
            emotion_label = req.emotion_label,
        ):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type='audio/pcm',
        headers={
            'X-Sample-Rate':  str(24000),
            'X-Channels':     '1',
            'X-Bit-Depth':    '16',
            'Cache-Control':  'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@app.post('/tts/synthesize')
async def tts_full(req: TTSRequest):
    """
    非流式合成接口（用于短文本或测试）。
    返回完整 Base64 编码 PCM。
    """
    import base64, asyncio
    loop = asyncio.get_event_loop()
    pcm = await loop.run_in_executor(
        None,
        lambda: tts.synthesize_full(
            req.text, req.speed, req.pitch,
            req.style, req.voice, req.emotion_label,
        )
    )
    return {
        'audio_b64':   base64.b64encode(pcm).decode(),
        'sample_rate': 24000,
        'channels':    1,
        'bit_depth':   16,
        'size_bytes':  len(pcm),
    }


@app.get('/tts/status')
async def tts_status():
    """查询当前播放状态（用于回声消除状态同步）。"""
    return {'is_playing': tts.is_playing}


@app.get('/health')
async def health():
    return {'status': 'ok', 'model': 'cosyvoice-v1'}
```

---

## 7. 回声消除协议

### 7.1 问题描述

```
❌ 不处理时的问题：

  AI 说话 → 扬声器播放 → 麦克风采集到 AI 声音
                                    │
                              STEP 1 识别为"用户输入"
                                    │
                         触发新一轮 LLM 回复 → 死循环
```

### 7.2 解决方案：麦克风门控

通过浏览器自定义事件在 STEP 1（useASR）和 STEP 4（useTTS）之间传递播放状态，TTS 播放期间暂停麦克风音频帧发送。

```
TTS 开始播放
     │
     ▼
dispatchEvent('tts-start')
     │
     ▼
useASR.ts 监听到 → ttsMuted = true
     │
     ▼
ScriptProcessorNode.onaudioprocess → 跳过发送（return 提前退出）
     │
     ▼
TTS 播放完毕
     │
     ▼
dispatchEvent('tts-end')
     │
     ▼
setTimeout 200ms → ttsMuted = false  ← 延迟恢复，等声音完全消散
```

### 7.3 门控时序图

```
时间轴：
  0ms      TTS 开始播放  → tts-start 事件  → ttsMuted = true
  |        [麦克风静音中]
  |        [AI 声音通过扬声器播放]
  |        [麦克风采集到 AI 声音，但不发送给 ASR]
  2500ms   TTS 播放完毕  → tts-end 事件
  2700ms   延迟 200ms   → ttsMuted = false → 麦克风恢复
```

> ⚠️ **200ms 恢复延迟**至关重要，房间混响会让声音在 TTS 结束后持续数百毫秒，过早恢复会捕捉到残留回声。

---

## 8. LLM-TTS 流水线并行

### 8.1 设计目标

用户感知延迟 = 说完话 → 听到 AI 开口的时间，目标压缩至 **~1.4s**。

### 8.2 时间分解（优化后）

```
0ms      VAD 检测到静音，触发 ASR 推理
300ms    ASR 输出转录文本（同时触发 STEP 2 情绪识别）
300ms    情绪识别完成（与 ASR 并发执行，几乎同时完成）
1100ms   LLM 输出第一个完整句子（句末标点出现）
1100ms   立即发起 TTS 合成请求（不等 LLM 全文生成）
1900ms   TTS 首包 PCM 到达前端
1900ms   WebAudio 开始播放第一块音频
─────────────────────────────────────────────────
用户感知延迟：约 1.4~2.0s（取决于 LLM 首句生成速度）
```

### 8.3 首句触发逻辑

在 STEP 3 的 `useLLM.ts` 中维护句子缓冲区，检测到首个句末标点时立即回调 STEP 4：

```typescript
// STEP 3 useLLM.ts 中的首句检测（已在 STEP 3 文档定义）
const SENTENCE_END = /[。！？.!?]/

function handleDeltaChunk(deltaText: string, ttsParams: TTSParams) {
  sentenceBuffer += deltaText

  // 检测完整句子
  const match = sentenceBuffer.match(/^([^。！？.!?]+[。！？.!?])/)
  if (match && !firstSentenceSent) {
    firstSentenceSent = true
    const firstSentence = match[1]
    sentenceBuffer = sentenceBuffer.slice(firstSentence.length)

    // 立即触发 STEP 4 合成首句
    onFirstSentence.value?.(firstSentence, ttsParams)
  }
}
```

### 8.4 多句排队播放

LLM 生成过程中可能触发多次 TTS 请求，前端使用播放队列保证有序无缝播放：

```typescript
// 播放队列：保证多句按顺序无缝拼接
const playQueue: Array<{ text: string; params: TTSParams }> = []
let   isQueueProcessing = false

async function enqueuePlay(text: string, params: TTSParams) {
  playQueue.push({ text, params })
  if (!isQueueProcessing) {
    await processQueue()
  }
}

async function processQueue() {
  isQueueProcessing = true
  while (playQueue.length > 0) {
    const item = playQueue.shift()!
    await playOnce(item.text, item.params)   // 等待当前句播放完毕
  }
  isQueueProcessing = false
}
```

---

## 9. HTTP 接口规范

### POST `/tts/stream`

**请求体：**
```json
{
  "text": "我在这里陪着您。",
  "speed": 0.85,
  "pitch": -2,
  "style": "gentle",
  "voice": "longxiaochun",
  "emotion_label": "sad"
}
```

**响应：**
```
Content-Type: audio/pcm
X-Sample-Rate: 24000
X-Channels: 1
X-Bit-Depth: 16

[二进制 PCM 流...]
```

**错误响应：**
```json
{ "detail": "text 不能为空" }
```

### POST `/tts/synthesize`（非流式，用于测试）

**响应：**
```json
{
  "audio_b64": "<Base64 encoded PCM>",
  "sample_rate": 24000,
  "channels": 1,
  "bit_depth": 16,
  "size_bytes": 48000
}
```

### GET `/tts/status`

```json
{ "is_playing": false }
```

---

## 10. 前端集成代码

### `composables/useTTS.ts`

```typescript
import { ref } from 'vue'

interface TTSParams {
  speed: number
  pitch: number
  style: string
}

export function useTTS(apiBase = 'http://localhost:8003') {
  const isPlaying = ref(false)

  // 回调：播放完毕时触发
  const onPlaybackDone = ref<(() => void) | null>(null)

  // WebAudio 上下文
  let audioContext: AudioContext | null = null
  let nextStartTime = 0   // 精确调度：下一块音频的开始时间

  // 播放队列（多句按顺序排队）
  const playQueue: Array<{ text: string; params: TTSParams; emotionLabel: string }> = []
  let isQueueProcessing = false


  // ── 公开接口：加入播放队列 ──────────────────────────────────────────────────

  async function speak(text: string, params: TTSParams, emotionLabel = 'neutral') {
    if (!text.trim()) return
    playQueue.push({ text, params, emotionLabel })
    if (!isQueueProcessing) {
      await processQueue()
    }
  }


  // ── 队列处理 ─────────────────────────────────────────────────────────────

  async function processQueue() {
    isQueueProcessing = true
    while (playQueue.length > 0) {
      const item = playQueue.shift()!
      await playOnce(item.text, item.params, item.emotionLabel)
    }
    isQueueProcessing = false
    isPlaying.value = false
    window.dispatchEvent(new CustomEvent('tts-end'))
    onPlaybackDone.value?.()
  }


  // ── 单句播放 ─────────────────────────────────────────────────────────────

  async function playOnce(text: string, params: TTSParams, emotionLabel: string) {
    isPlaying.value = true
    window.dispatchEvent(new CustomEvent('tts-start'))

    // 初始化 AudioContext（每次对话新建，避免 suspended 状态）
    if (!audioContext || audioContext.state === 'closed') {
      audioContext = new AudioContext({ sampleRate: 24000 })
      nextStartTime = audioContext.currentTime
    }

    try {
      const res = await fetch(`${apiBase}/tts/stream`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          text,
          speed:         params.speed,
          pitch:         params.pitch,
          style:         params.style,
          voice:         'longxiaochun',
          emotion_label: emotionLabel,
        }),
      })

      if (!res.ok) throw new Error(`TTS 请求失败: HTTP ${res.status}`)
      if (!res.body) throw new Error('无响应体')

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

        // 按帧播放，保证流畅
        while (pcmBuffer.length >= FRAME_BYTES) {
          const frame  = pcmBuffer.slice(0, FRAME_BYTES)
          pcmBuffer    = pcmBuffer.slice(FRAME_BYTES)
          schedulePCMFrame(audioContext!, frame)
        }
      }

      // 播放剩余不足一帧的数据
      if (pcmBuffer.length > 0) {
        schedulePCMFrame(audioContext!, pcmBuffer)
      }

      // 等待已调度的音频全部播放完毕
      const waitMs = Math.max(0, (nextStartTime - audioContext.currentTime + 0.1) * 1000)
      await sleep(waitMs)

    } catch (err) {
      console.error('[TTS] 播放失败:', err)
    }
  }


  // ── PCM 帧调度播放（精确时序）──────────────────────────────────────────────

  function schedulePCMFrame(ctx: AudioContext, pcmData: Uint8Array) {
    const int16   = new Int16Array(pcmData.buffer, pcmData.byteOffset, pcmData.byteLength / 2)
    const float32 = new Float32Array(int16.length)

    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768.0
    }

    const audioBuffer = ctx.createBuffer(1, float32.length, 24000)
    audioBuffer.copyToChannel(float32, 0)

    const source = ctx.createBufferSource()
    source.buffer = audioBuffer
    source.connect(ctx.destination)

    // 精确调度：在上一帧结束的时间点开始播放，保证无缝拼接
    const startAt   = Math.max(ctx.currentTime, nextStartTime)
    source.start(startAt)
    nextStartTime = startAt + audioBuffer.duration
  }


  // ── 停止播放 ─────────────────────────────────────────────────────────────

  function stop() {
    playQueue.length      = 0
    isQueueProcessing     = false
    isPlaying.value       = false
    audioContext?.close()
    audioContext          = null
    nextStartTime         = 0
    window.dispatchEvent(new CustomEvent('tts-end'))
  }


  // ── 工具 ─────────────────────────────────────────────────────────────────

  function sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms))
  }

  return { isPlaying, onPlaybackDone, speak, stop }
}
```

### 主组件集成示例 `App.vue`（四步串联）

```typescript
// 在主组件中将 STEP 1~4 串联起来
import { useASR }  from './composables/useASR'
import { useLLM }  from './composables/useLLM'
import { useTTS }  from './composables/useTTS'

// （假设 emotion 状态由 STEP 2 HTTP 请求填充）
const currentEmotion = ref<EmotionResult | null>(null)

const asr = useASR()
const llm = useLLM()
const tts = useTTS()

// ── STEP 1 → STEP 2 → STEP 3 串联 ─────────────────────────────────────────
asr.onTranscript.value = async (transcriptEvent) => {
  // STEP 2：情绪识别
  const emotionRes = await fetch('http://localhost:8001/emotion/analyze', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({
      audio_b64:  transcriptEvent.audio_b64,
      sample_rate: 16000,
      session_id: 'default',
    }),
  })
  currentEmotion.value = await emotionRes.json()

  // STEP 3：LLM 流式回复
  await llm.streamReply(transcriptEvent.text, currentEmotion.value!)
}

// ── STEP 3 → STEP 4 串联 ────────────────────────────────────────────────────
// 首句立即触发 TTS（流水线并行）
llm.onFirstSentence.value = (sentence, ttsParams) => {
  tts.speak(sentence, ttsParams, currentEmotion.value?.label ?? 'neutral')
}

// LLM 全文完成后，将剩余句子加入播放队列
llm.onReplyDone.value = (event) => {
  // 提取剩余句子（首句之后的部分）
  const remainingText = extractRemainingText(event.full_text)
  if (remainingText.trim()) {
    tts.speak(remainingText, event.tts_params, event.emotion_label)
  }
}

// ── 开始 / 停止对话 ───────────────────────────────────────────────────────
async function startConversation() {
  await asr.start()
  // 同时重置 STEP 2、3 历史
  await fetch('http://localhost:8001/emotion/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: 'default' }),
  })
  await llm.resetSession()
}

function stopConversation() {
  asr.stop()
  tts.stop()
}
```

---

## 11. 全链路时序图

```
用户                 STEP1(ASR)        STEP2(情绪)      STEP3(LLM)       STEP4(TTS)
 │                      │                  │                │                │
 │── 开始说话 ──────────▶│                  │                │                │
 │                      │ VAD检测语音       │                │                │
 │                      │ 累积PCM音频       │                │                │
 │── 停止说话 ──────────▶│                  │                │                │
 │                   (0ms)                 │                │                │
 │                      │── 并发触发 ──────▶│                │                │
 │                      │  情绪分析        │                │                │
 │                   (300ms)               │                │                │
 │                      │── 转录文本 ────────────────────────▶│                │
 │                      │              (300ms)               │                │
 │                      │                  │── 情绪结果 ────▶│                │
 │                      │                  │                │ 构建Prompt      │
 │                      │                  │                │ 调用Qwen API    │
 │                   (1100ms)              │                │                │
 │                      │                  │         首句生成完毕              │
 │                      │                  │                │── 首句 ────────▶│
 │                      │                  │                │              调用TTS API
 │                      │                  │                │ 继续生成剩余    │
 │                   (1900ms)              │                │                │
 │◀─ 听到AI说话 ─────────────────────────────────────────────────────────────│
 │                      │                  │         生成完毕(~2200ms)        │
 │                      │                  │                │── 剩余文本 ────▶│
 │                      │                  │                │             排队播放
 │                   (2200ms~)             │                │                │
 │◀─ 继续听AI说话 ────────────────────────────────────────────────────────────│
 │                      │                  │                │           播放完毕
 │                      │                  │                │                │── tts-end
 │                      │ ttsMuted=false   │                │                │
 │── 继续说话 ──────────▶│                  │                │                │
```

---

## 12. TDD 验收测试

### `tests/test_step4.py`

```python
import pytest
import numpy as np
from unittest.mock import MagicMock, patch, PropertyMock
from tts_service import TTSService
from config import (
    SPEED_MIN, SPEED_MAX, PITCH_MIN, PITCH_MAX,
    STYLE_MAP, EMOTION_VOICE_MAP,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    """每个测试用例使用独立的 TTSService 实例，mock 掉 API 调用"""
    service = TTSService()
    return service


def make_pcm_chunk(duration_ms: int = 100, sample_rate: int = 24000) -> bytes:
    """生成测试用 PCM 数据块（静音）"""
    samples = int(sample_rate * duration_ms / 1000)
    return np.zeros(samples, dtype=np.int16).tobytes()


# ─── TC-01: 参数校验 ──────────────────────────────────────────────────────────

class TestParameterValidation:

    def test_empty_text_yields_nothing(self, svc):
        """TC-01: 空文本不调用 API，不产生任何输出"""
        with patch.object(svc, '_call_api') as mock_api:
            result = list(svc.synthesize_stream(''))
            mock_api.assert_not_called()
            assert result == []

    def test_whitespace_text_yields_nothing(self, svc):
        """TC-02: 纯空白文本不产生输出"""
        with patch.object(svc, '_call_api') as mock_api:
            list(svc.synthesize_stream('   \n  '))
            mock_api.assert_not_called()

    def test_speed_clamped_to_min(self, svc):
        """TC-03: 语速低于下限时被裁剪到 SPEED_MIN"""
        captured_speed = []
        def mock_call(text, speed, pitch, style, voice):
            captured_speed.append(speed)
            return iter([])
        with patch.object(svc, '_call_api', side_effect=mock_call):
            list(svc.synthesize_stream('测试', speed=0.1))
        assert captured_speed[0] == SPEED_MIN

    def test_speed_clamped_to_max(self, svc):
        """TC-04: 语速高于上限时被裁剪到 SPEED_MAX"""
        captured_speed = []
        def mock_call(text, speed, pitch, style, voice):
            captured_speed.append(speed)
            return iter([])
        with patch.object(svc, '_call_api', side_effect=mock_call):
            list(svc.synthesize_stream('测试', speed=5.0))
        assert captured_speed[0] == SPEED_MAX

    def test_pitch_clamped_to_range(self, svc):
        """TC-05: 音调超出范围时被裁剪"""
        captured_pitch = []
        def mock_call(text, speed, pitch, style, voice):
            captured_pitch.append(pitch)
            return iter([])
        with patch.object(svc, '_call_api', side_effect=mock_call):
            list(svc.synthesize_stream('测试', pitch=99))
        assert captured_pitch[0] == PITCH_MAX


# ─── TC-02: is_playing 状态管理 ───────────────────────────────────────────────

class TestPlayingState:

    def test_is_playing_true_during_synthesis(self, svc):
        """TC-06: 合成过程中 is_playing 为 True"""
        states_during = []
        def mock_call(text, speed, pitch, style, voice):
            states_during.append(svc.is_playing)
            yield make_pcm_chunk()
        with patch.object(svc, '_call_api', side_effect=mock_call):
            list(svc.synthesize_stream('测试'))
        assert True in states_during

    def test_is_playing_false_after_synthesis(self, svc):
        """TC-07: 合成完成后 is_playing 复位为 False"""
        with patch.object(svc, '_call_api', return_value=iter([make_pcm_chunk()])):
            list(svc.synthesize_stream('测试'))
        assert svc.is_playing is False

    def test_is_playing_false_after_exception(self, svc):
        """TC-08: 合成抛出异常后 is_playing 仍然复位为 False（finally 保证）"""
        def mock_call(*args, **kwargs):
            raise RuntimeError("API 错误")
        with patch.object(svc, '_call_api', side_effect=mock_call):
            with pytest.raises(RuntimeError):
                list(svc.synthesize_stream('测试'))
        assert svc.is_playing is False


# ─── TC-03: 情绪音色映射 ─────────────────────────────────────────────────────

class TestEmotionVoiceMapping:

    def test_happy_uses_lively_voice(self, svc):
        """TC-09: 快乐情绪使用活泼音色"""
        captured_voice = []
        def mock_call(text, speed, pitch, style, voice):
            captured_voice.append(voice)
            return iter([])
        with patch.object(svc, '_call_api', side_effect=mock_call):
            list(svc.synthesize_stream('测试', emotion_label='happy'))
        assert captured_voice[0] == EMOTION_VOICE_MAP['happy']

    def test_all_emotions_have_voice_mapping(self):
        """TC-10: 所有情绪标签都有音色映射"""
        labels = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised', '_crisis']
        for label in labels:
            assert label in EMOTION_VOICE_MAP, f"缺少音色映射: {label}"

    def test_all_styles_in_style_map(self):
        """TC-11: 所有风格标签都在 STYLE_MAP 中"""
        required_styles = ['gentle', 'calm', 'cheerful', 'neutral']
        for style in required_styles:
            assert style in STYLE_MAP, f"缺少风格映射: {style}"


# ─── TC-04: 分句逻辑 ─────────────────────────────────────────────────────────

class TestSentenceSplitting:

    def test_short_text_not_split(self, svc):
        """TC-12: 短文本（≤200字）不分句，直接合成"""
        text = '我在这里陪着您。'
        sentences = svc._split_sentences(text)
        assert len(sentences) == 1
        assert sentences[0] == text

    def test_multiple_sentences_split_correctly(self, svc):
        """TC-13: 多句文本按标点正确分句"""
        text = '我在这里陪着您。听起来今天很难过。能跟我说说吗？'
        sentences = svc._split_sentences(text)
        assert len(sentences) == 3
        assert sentences[0] == '我在这里陪着您。'
        assert sentences[1] == '听起来今天很难过。'
        assert sentences[2] == '能跟我说说吗？'

    def test_text_without_punctuation_returned_as_single(self, svc):
        """TC-14: 无标点文本作为单个句子返回"""
        text = '没有标点的文本'
        sentences = svc._split_sentences(text)
        assert len(sentences) == 1
        assert sentences[0] == text

    def test_sentence_with_trailing_text_captured(self, svc):
        """TC-15: 末尾无标点的文本被追加到句子列表"""
        text = '第一句话。第二句话'
        sentences = svc._split_sentences(text)
        assert len(sentences) == 2
        assert sentences[1] == '第二句话'


# ─── TC-05: 输出数据格式 ─────────────────────────────────────────────────────

class TestOutputFormat:

    def test_synthesize_stream_yields_bytes(self, svc):
        """TC-16: synthesize_stream 产出 bytes 类型数据"""
        pcm = make_pcm_chunk()
        with patch.object(svc, '_call_api', return_value=iter([pcm])):
            chunks = list(svc.synthesize_stream('测试'))
        assert all(isinstance(c, bytes) for c in chunks)

    def test_synthesize_full_returns_bytes(self, svc):
        """TC-17: synthesize_full 返回 bytes 类型"""
        pcm = make_pcm_chunk()
        with patch.object(svc, '_call_api', return_value=iter([pcm])):
            result = svc.synthesize_full('测试')
        assert isinstance(result, bytes)

    def test_synthesize_full_concatenates_chunks(self, svc):
        """TC-18: synthesize_full 正确拼接多个 PCM 块"""
        chunk1 = make_pcm_chunk(100)
        chunk2 = make_pcm_chunk(100)
        with patch.object(svc, '_call_api', return_value=iter([chunk1, chunk2])):
            result = svc.synthesize_full('测试')
        assert len(result) == len(chunk1) + len(chunk2)


# ─── TC-06: FastAPI 接口 ─────────────────────────────────────────────────────

class TestFastAPIEndpoints:

    @pytest.mark.asyncio
    async def test_stream_endpoint_returns_audio_pcm(self):
        """TC-19: /tts/stream 返回 Content-Type: audio/pcm"""
        from fastapi.testclient import TestClient
        from tts_server import app
        from unittest.mock import patch

        pcm = make_pcm_chunk()
        with patch('tts_server.tts.synthesize_stream', return_value=iter([pcm])):
            client = TestClient(app)
            res = client.post('/tts/stream', json={
                'text': '测试文本',
                'speed': 1.0,
                'pitch': 0,
                'style': 'neutral',
                'voice': 'longxiaochun',
                'emotion_label': 'neutral',
            })
        assert res.status_code == 200
        assert 'audio/pcm' in res.headers.get('content-type', '')

    @pytest.mark.asyncio
    async def test_stream_endpoint_rejects_empty_text(self):
        """TC-20: /tts/stream 拒绝空文本，返回 400"""
        from fastapi.testclient import TestClient
        from tts_server import app

        client = TestClient(app)
        res = client.post('/tts/stream', json={
            'text': '',
            'speed': 1.0, 'pitch': 0, 'style': 'neutral',
            'voice': 'longxiaochun', 'emotion_label': 'neutral',
        })
        assert res.status_code == 400

    def test_status_endpoint_returns_is_playing(self):
        """TC-21: /tts/status 返回 is_playing 字段"""
        from fastapi.testclient import TestClient
        from tts_server import app

        client = TestClient(app)
        res = client.get('/tts/status')
        assert res.status_code == 200
        assert 'is_playing' in res.json()
```

### 验收标准汇总

| ID | 描述 | 通过条件 |
|----|------|----------|
| TC-01 | 空文本不调用 API | `_call_api` 未被调用 |
| TC-02 | 纯空白文本不输出 | 同上 |
| TC-03 | 语速低于下限被裁剪 | `speed == SPEED_MIN` |
| TC-04 | 语速高于上限被裁剪 | `speed == SPEED_MAX` |
| TC-05 | 音调超出范围被裁剪 | `pitch == PITCH_MAX` |
| TC-06 | 合成中 is_playing 为 True | states_during 含 True |
| TC-07 | 合成后 is_playing 复位 | `is_playing == False` |
| TC-08 | 异常后 is_playing 复位 | finally 保证复位 |
| TC-09 | 快乐情绪使用活泼音色 | voice == 映射值 |
| TC-10 | 所有情绪有音色映射 | 8 个 label 均存在 |
| TC-11 | 所有风格在映射表 | 4 个 style 均存在 |
| TC-12 | 短文本不分句 | sentences 长度 == 1 |
| TC-13 | 多句正确分句 | sentences 长度 == 3 |
| TC-14 | 无标点单句返回 | sentences 长度 == 1 |
| TC-15 | 末尾无标点文本被捕获 | sentences 长度 == 2 |
| TC-16 | stream 产出 bytes | 类型验证通过 |
| TC-17 | full 返回 bytes | 类型验证通过 |
| TC-18 | full 正确拼接 | 长度 == chunk1 + chunk2 |
| TC-19 | 接口返回 audio/pcm | content-type 正确 |
| TC-20 | 空文本返回 400 | status_code == 400 |
| TC-21 | status 返回 is_playing | 字段存在 |

---

## 附录 A：服务启动命令

```bash
# 开发模式
uvicorn tts_server:app --host 0.0.0.0 --port 8003 --reload

# 生产模式
uvicorn tts_server:app --host 0.0.0.0 --port 8003 --workers 1
```

---

## 附录 B：四步服务端口汇总

| 模块 | 服务 | 端口 | 协议 |
|------|------|------|------|
| STEP 1 | ASR 服务 | 8000 | WebSocket |
| STEP 2 | 情绪识别服务 | 8001 | HTTP |
| STEP 3 | LLM 回复服务 | 8002 | HTTP + SSE |
| STEP 4 | TTS 合成服务 | 8003 | HTTP 流式 |

---

## 附录 C：一键启动脚本

```bash
#!/bin/bash
# start_all.sh — 启动全部四个服务

echo "启动 STEP 1 — ASR 服务..."
cd step1_asr && uvicorn asr_server:app --port 8000 --workers 1 &

echo "启动 STEP 2 — 情绪识别服务..."
cd step2_emotion && uvicorn emotion_server:app --port 8001 --workers 1 &

echo "启动 STEP 3 — LLM 回复服务..."
cd step3_llm && uvicorn llm_server:app --port 8002 --workers 1 &

echo "启动 STEP 4 — TTS 合成服务..."
cd step4_tts && uvicorn tts_server:app --port 8003 --workers 1 &

echo "全部服务已启动 ✅"
echo "前端访问地址: http://localhost:5173"

wait
```
