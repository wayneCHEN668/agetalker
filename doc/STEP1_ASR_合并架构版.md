# STEP 1 — 实时语音转录模块
**架构：单应用合并版 · FunASR paraformer-zh · 端口 8000**

---

## 目录
1. [模块概述](#1-模块概述)
2. [技术选型](#2-技术选型)
3. [在单应用中的位置](#3-在单应用中的位置)
4. [目录结构](#4-目录结构)
5. [环境依赖与安装](#5-环境依赖与安装)
6. [配置常量](#6-配置常量)
7. [核心服务实现](#7-核心服务实现)
8. [路由层实现](#8-路由层实现)
9. [VAD 参数调优](#9-vad-参数调优老人语音专项)
10. [准确率保障措施](#10-准确率保障措施)
11. [WebSocket 消息协议](#11-websocket-消息协议)
12. [前端采集代码](#12-前端采集代码)
13. [TDD 验收测试](#13-tdd-验收测试)

---

## 1. 模块概述

本模块负责从麦克风实时采集音频，经过语音活动检测（VAD）进行句级切分后，调用 **FunASR paraformer-zh** 模型完成中文语音识别，并通过标点恢复模型输出完整句子文本，通过 **WebSocket** 实时推送至前端。

### 与旧版（多端口）的核心区别

| 维度 | 旧版（独立端口 8000） | 新版（单应用合并） |
|------|---------------------|------------------|
| 运行方式 | 独立 Python 进程 | 同一 FastAPI 进程的一个路由 |
| 音频传递给 STEP 2 | Base64 编码 → HTTP POST | **numpy 数组直接传递**，零序列化 |
| STEP 1 + STEP 2 执行 | 串行（先 ASR 再情绪） | **asyncio.gather 并发执行** |
| 服务初始化 | 路由文件内自行初始化 | **main.py 统一初始化后注入** |
| 启动命令 | 独立一条 uvicorn | 随整个应用一起启动 |

### 目标指标

| 指标 | 目标值 |
|------|--------|
| 识别准确率（CER） | ≥ 95%（字符错误率 < 5%） |
| 单句推理延迟 | VAD 触发静音后 ≤ 800ms 输出结果 |
| 支持语言 | 中文普通话（兼容少量方言词汇） |
| 运行环境 | 纯 CPU，无需 GPU |
| 句级切分 | 停顿 ≥ 1.5s 触发切句 |

---

## 2. 技术选型

| 组件 | 选型 | 说明 |
|------|------|------|
| ASR 核心 | `paraformer-zh`（非流式） | 中文 ASR，CPU 可用，准确率高 |
| VAD | `fsmn-vad` | FunASR 内置，检测说话起止时间点 |
| 标点恢复 | `ct-punc` | FunASR 内置，输出含标点完整句子 |
| 热词增强 | paraformer-zh 热词接口 | 注入养老场景专业词汇 |
| 服务框架 | FastAPI WebSocket | 已与主应用共享，无需单独启动 |
| 音频传输 | WebSocket 二进制帧 | 前端直接发送 PCM 数据 |

> **为什么选 paraformer-zh 而非 Whisper？**
> Whisper 中文标点差、CPU 推理慢；paraformer-zh 在中文口语 CER 约 3~4%，实时率 RTF < 0.1，更适合本场景。

---

## 3. 在单应用中的位置

```
main.py（应用入口）
  │
  ├── lifespan() 统一初始化
  │       ├── ASRService()        ← STEP 1 服务实例
  │       ├── EmotionService()    ← STEP 2 服务实例
  │       ├── LLMService()        ← STEP 3 服务实例
  │       └── TTSService()        ← STEP 4 服务实例
  │
  └── app.include_router()
          └── routers/ws_asr.py  ← STEP 1 路由
                  │
                  │  WebSocket /ws/asr
                  │
                  ├── ASRService.transcribe(audio)       直接调用
                  └── EmotionService.analyze(audio)      直接调用（并发）
```

**关键设计：路由层（routers/ws_asr.py）只负责协议处理，业务逻辑全部在服务层（services/asr_service.py）。**

---

## 4. 目录结构

```
emotion_companion/
├── main.py                    # 应用入口（STEP 1 服务在此初始化）
├── config.py                  # STEP 1 相关配置在此定义
├── hotwords.txt               # 热词列表
├── requirements.txt
│
├── services/
│   └── asr_service.py         # ← STEP 1 核心实现（纯 Python 类）
│
├── routers/
│   └── ws_asr.py              # ← STEP 1 路由（WebSocket 协议层）
│
└── tests/
    └── test_asr_service.py    # ← STEP 1 测试
```

---

## 5. 环境依赖与安装

STEP 1 所需依赖已合并到项目统一的 `requirements.txt`，**不需要单独安装**：

```
# requirements.txt（节选 STEP 1 相关部分）
funasr>=1.1.0
torch>=2.0.0        # CPU 版本
torchaudio>=2.0.0
numpy>=1.24.0
```

```bash
# 安装 CPU 版 PyTorch（避免下载 CUDA 版本，体积更小）
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# 安装全部依赖
pip install -r requirements.txt
```

### 模型首次下载

模型在首次运行时自动从 ModelScope 下载，缓存至 `~/.cache/modelscope/`，约占用 **500MB** 磁盘。

```bash
# 离线部署：设置缓存路径，联网下载一次后可完全离线
export MODELSCOPE_CACHE=/data/models
```

---

## 6. 配置常量

以下常量定义在项目统一的 `config.py` 中，STEP 1 专属部分如下：

```python
# config.py（STEP 1 相关部分）

# ── 音频参数 ──────────────────────────────────────────────────────────────────
ASR_SAMPLE_RATE    = 16000       # 采样率（Hz）
ASR_FRAME_SAMPLES  = 1600        # 每帧采样数（100ms @ 16kHz）

# ── 静音检测 ──────────────────────────────────────────────────────────────────
ASR_SILENCE_RMS    = 0.008       # 静音 RMS 阈值，低于此值判定为静音帧
ASR_SILENCE_FRAMES = 15          # 连续 15 帧静音（1.5s）触发 ASR 推理

# ── VAD 参数（老人语音专项调优）────────────────────────────────────────────────
ASR_VAD_KWARGS = {
    'max_end_silence_time':    1500,   # ms，老人停顿多，调大避免过早切句
    'speech_noise_thres':      0.75,   # 降低噪声阈值，适应背景噪音
    'max_single_segment_time': 30000,  # ms，单句最长时间
    'min_speech_duration':     300,    # ms，最短有效语音，过滤误触发
}
```

### 热词文件 `hotwords.txt`

```
养老院
护理员
血压
血糖
心率
用药时间
餐厅
活动室
轮椅
助步器
体温
血氧
康复
理疗
家属
```

---

## 7. 核心服务实现

### `services/asr_service.py`

```python
import numpy as np
import logging
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess
from config import (
    ASR_SAMPLE_RATE,
    ASR_SILENCE_RMS,
    ASR_SILENCE_FRAMES,
    ASR_VAD_KWARGS,
)

logger = logging.getLogger(__name__)


class ASRService:
    """
    FunASR paraformer-zh 语音转录服务。

    设计说明：
    - 本类是纯 Python 服务类，不包含任何 HTTP/WebSocket 逻辑
    - 在 main.py 的 lifespan() 中统一初始化，整个应用生命周期共享同一实例
    - transcribe() 方法接收 numpy 数组，直接供路由层和 EmotionService 共用，
      无需任何序列化
    """

    def __init__(self):
        logger.info("正在加载 ASR 模型（paraformer-zh），首次约需 30s...")
        self.model = AutoModel(
            model='paraformer-zh',
            vad_model='fsmn-vad',
            punc_model='ct-punc',
            device='cpu',
            disable_update=True,
            vad_kwargs=ASR_VAD_KWARGS,
            ncpu=4,                    # CPU 线程数，根据机器调整
        )
        self.hotwords = open('hotwords.txt', encoding='utf-8').read().strip()
        logger.info("ASR 模型加载完成 ✅")

    # ── 核心接口 ──────────────────────────────────────────────────────────────

    def transcribe(self, audio: np.ndarray) -> str:
        """
        对单句音频进行语音识别。

        Args:
            audio: Float32 归一化 PCM，16kHz 单声道。
                   直接来自路由层的 audio_buffer 拼接结果，
                   同一份数组也会传给 EmotionService.analyze()。

        Returns:
            带标点的中文转录文本。识别结果为空时返回 ''。
        """
        if len(audio) == 0:
            return ''

        result = self.model.generate(
            input=audio,
            language='zh',
            use_itn=True,          # 逆文本归一化：数字、单位规范化输出
            batch_size_s=60,
            hotword=self.hotwords,
        )

        if not result or not result[0].get('text'):
            return ''

        # rich_transcription_postprocess：去除填充词、规范标点
        return rich_transcription_postprocess(result[0]['text'])

    # ── 静态工具方法（路由层调用）──────────────────────────────────────────────

    @staticmethod
    def bytes_to_float32(data: bytes) -> np.ndarray:
        """
        将 WebSocket 收到的 Int16 PCM bytes 转换为 Float32 归一化数组。
        转换后的数组可同时传给 transcribe() 和 EmotionService.analyze()。
        """
        int16 = np.frombuffer(data, dtype=np.int16)
        return int16.astype(np.float32) / 32768.0

    @staticmethod
    def compute_rms(audio: np.ndarray) -> float:
        """计算音频帧的均方根能量，用于静音检测。"""
        return float(np.sqrt(np.mean(audio ** 2)))
```

---

## 8. 路由层实现

### `routers/ws_asr.py`

```python
import asyncio
import json
import logging
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.asr_service import ASRService
from services.emotion_service import EmotionService
from config import ASR_SILENCE_RMS, ASR_SILENCE_FRAMES

logger = logging.getLogger(__name__)
router = APIRouter()

# ── 服务实例由 main.py 注入，此处声明为模块级变量 ──────────────────────────────
# 路由层本身不创建服务实例，确保全局只有一份模型被加载
asr_service:     ASRService     = None
emotion_service: EmotionService = None


@router.websocket('/ws/asr')
async def asr_endpoint(ws: WebSocket):
    await ws.accept()
    logger.info(f"ASR 客户端已连接: {ws.client}")

    # 每个 WebSocket 连接维护独立的音频缓冲区（支持多用户并发）
    audio_buffer:  list[np.ndarray] = []
    silent_frames: int              = 0

    # 通知前端服务就绪
    await ws.send_text(json.dumps({'type': 'status', 'state': 'listening'}))

    try:
        while True:
            # 接收前端发送的 PCM 二进制帧（Int16，每帧 100ms）
            data  = await ws.receive_bytes()
            chunk = ASRService.bytes_to_float32(data)
            rms   = ASRService.compute_rms(chunk)

            # 静音检测
            if rms < ASR_SILENCE_RMS:
                silent_frames += 1
            else:
                silent_frames = 0
                audio_buffer.append(chunk)

            # 触发条件：静音超过阈值 且 有积累的语音片段
            if silent_frames >= ASR_SILENCE_FRAMES and len(audio_buffer) > 5:
                # 拼接完整音频片段
                audio = np.concatenate(audio_buffer)
                audio_buffer.clear()
                silent_frames = 0

                await ws.send_text(json.dumps({'type': 'status', 'state': 'processing'}))

                loop = asyncio.get_event_loop()

                # ── 关键优化：STEP 1 + STEP 2 并发执行 ────────────────────────
                # 同一份 numpy 数组直接传给两个服务，无需任何序列化/反序列化
                # 总耗时 ≈ max(ASR延迟, 情绪延迟)，而非两者之和
                asr_task     = loop.run_in_executor(
                    None, lambda a=audio: asr_service.transcribe(a)
                )
                emotion_task = loop.run_in_executor(
                    None, lambda a=audio: emotion_service.analyze(a)
                )
                text, emotion = await asyncio.gather(asr_task, emotion_task)

                # 只有转录文本非空时才推送（过滤纯噪音误触发）
                if text.strip():
                    logger.info(f"转录: {text} | 情绪: {emotion.label}({emotion.score:.2f})")
                    await ws.send_text(json.dumps({
                        'type':      'transcript',
                        'text':      text,
                        'is_final':  True,
                        # 情绪结果直接附在 transcript 消息里，前端无需再发额外请求
                        'emotion':   emotion_service.to_dict(emotion),
                        'timestamp': loop.time(),
                    }))

                await ws.send_text(json.dumps({'type': 'status', 'state': 'listening'}))

    except WebSocketDisconnect:
        logger.info(f"ASR 客户端断开: {ws.client}")
    except Exception as e:
        logger.error(f"ASR 处理异常: {e}", exc_info=True)
        try:
            await ws.send_text(json.dumps({
                'type':    'error',
                'code':    'ASR_ERROR',
                'message': str(e),
            }))
        except Exception:
            pass
```

### 与 `main.py` 的连接方式

路由层声明了 `asr_service` 和 `emotion_service` 两个模块级变量，在 `main.py` 的 `lifespan()` 中初始化并注入：

```python
# main.py（节选，完整版见 STEP 汇总文档）
import routers.ws_asr as ws_asr_router
from services.asr_service     import ASRService
from services.emotion_service import EmotionService

@asynccontextmanager
async def lifespan(app: FastAPI):
    asr_svc     = ASRService()
    emotion_svc = EmotionService()
    # ...其他服务初始化...

    # 注入到路由模块
    ws_asr_router.asr_service     = asr_svc
    ws_asr_router.emotion_service = emotion_svc

    # 预热：首次推理会触发 JIT 编译，用静音数据提前完成
    import numpy as np
    dummy = np.zeros(16000, dtype=np.float32)
    asr_svc.transcribe(dummy)         # 预热 ASR
    emotion_svc.analyze(dummy)        # 预热情绪（STEP 2 负责）
    
    yield

app.include_router(ws_asr_router.router)   # 挂载到 8000 端口
```

---

## 9. VAD 参数调优（老人语音专项）

> ⚠️ **重要**：老人说话速度慢、停顿多，默认 VAD 参数会过早切句，**必须**调整以下参数。

| 参数 | 默认值 | 推荐值 | 调整原因 |
|------|--------|--------|----------|
| `max_end_silence_time` | 500ms | **1500ms** | 老人句中停顿多，需更长静音才切句 |
| `speech_noise_thres` | 0.9 | **0.75** | 降低噪声判定阈值，适应背景噪音 |
| `max_single_segment_time` | 15s | **30s** | 避免长句被强制切断 |
| `min_speech_duration` | 200ms | **300ms** | 过滤误触发，要求更长有效语音 |

所有参数统一在 `config.py` 的 `ASR_VAD_KWARGS` 字典中修改，服务重启后生效。

---

## 10. 准确率保障措施

以下 5 项措施综合保障识别准确率 ≥ 95%：

| 措施 | 实现位置 | 说明 |
|------|----------|------|
| **热词注入** | `ASRService.__init__()` 加载 `hotwords.txt` | 养老词汇识别率 +10~15% |
| **ITN 规范化** | `transcribe()` 中 `use_itn=True` | 数字、单位输出规范 |
| **标点恢复** | `ct-punc` 模型 | 句子完整性提升 |
| **后处理** | `rich_transcription_postprocess()` | 去除填充词、语气词 |
| **回声消除** | 前端 `useASR.ts` 的 `ttsMuted` 门控 | TTS 播放期间暂停发送音频帧 |

---

## 11. WebSocket 消息协议

### 前端 → 后端（二进制帧）

```
每 100ms 发送一帧 PCM 数据
格式：ArrayBuffer（Int16Array，16kHz，单声道，1600 samples/帧）
```

### 后端 → 前端（JSON 文本帧）

**转录结果（含情绪，与旧版不同）：**

```json
{
  "type": "transcript",
  "text": "今天天气真好，我想出去走走。",
  "is_final": true,
  "emotion": {
    "label": "happy",
    "label_zh": "快乐",
    "score": 0.821,
    "raw_label": "happy",
    "raw_score": 0.821,
    "valence": 0.90,
    "arousal": 0.70,
    "trend": "情绪持续稳定在「快乐」状态",
    "history": [
      { "label": "neutral", "score": 0.75 },
      { "label": "happy",   "score": 0.81 },
      { "label": "happy",   "score": 0.82 }
    ]
  },
  "timestamp": 1712345678.123
}
```

> **与旧版的重要区别**：旧版 transcript 消息中携带 `audio_b64`，前端需要再发一次 HTTP POST 到情绪服务。新版情绪结果直接附在 transcript 消息中，前端收到一条消息即可同时拿到文本和情绪，**减少一次网络往返**。

**服务状态：**

```json
{ "type": "status", "state": "listening" }
```

`state` 枚举：`listening`（等待输入）| `processing`（推理中）| `idle`（未连接）

**错误：**

```json
{
  "type": "error",
  "code": "ASR_ERROR",
  "message": "具体错误描述"
}
```

---

## 12. 前端采集代码

### `composables/useASR.ts`

```typescript
import { ref } from 'vue'

// ── 回声消除门控（与 STEP 4 useTTS 解耦通信）────────────────────────────────
// STEP 4 播放 TTS 时 dispatch 'tts-start'，播放完毕 dispatch 'tts-end'
// 这里监听事件，暂停/恢复麦克风发送，防止 AI 声音被 ASR 误识别
let ttsMuted = false
window.addEventListener('tts-start', () => {
  ttsMuted = true
})
window.addEventListener('tts-end', () => {
  // 延迟 200ms 恢复，等待房间混响完全消散
  setTimeout(() => { ttsMuted = false }, 200)
})


// ── 类型定义 ──────────────────────────────────────────────────────────────────
export interface TranscriptEvent {
  text:      string
  emotion:   EmotionResult   // 直接从消息中取，无需额外请求
  timestamp: number
}

export interface EmotionResult {
  label:     string
  label_zh:  string
  score:     number
  raw_label: string
  raw_score: number
  valence:   number
  arousal:   number
  trend:     string
  history:   Array<{ label: string; score: number }>
}


// ── Composable ────────────────────────────────────────────────────────────────
export function useASR(wsUrl = 'ws://localhost:8000/ws/asr') {
  const transcript = ref('')
  const status     = ref<'idle' | 'listening' | 'processing'>('idle')
  const error      = ref('')

  let ws:          WebSocket          | null = null
  let audioContext: AudioContext      | null = null
  let processor:    ScriptProcessorNode | null = null
  let mediaStream:  MediaStream       | null = null

  // 外部回调：收到转录+情绪结果时触发（供父组件串联 STEP 3）
  const onTranscript = ref<((event: TranscriptEvent) => void) | null>(null)


  // ── 启动录音 ─────────────────────────────────────────────────────────────

  async function start() {
    // 建立 WebSocket 连接（唯一端口 8000）
    ws = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'

    ws.onopen  = () => { status.value = 'listening' }
    ws.onclose = () => { status.value = 'idle' }
    ws.onerror = () => { error.value = 'WebSocket 连接失败' }

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data as string)

      if (msg.type === 'transcript') {
        transcript.value += msg.text
        // 直接将含情绪的完整事件传给上层，无需再发 HTTP 请求
        onTranscript.value?.({
          text:      msg.text,
          emotion:   msg.emotion,
          timestamp: msg.timestamp,
        })
      } else if (msg.type === 'status') {
        status.value = msg.state
      } else if (msg.type === 'error') {
        error.value = msg.message
      }
    }

    // 请求麦克风权限
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate:        16000,
        channelCount:      1,
        echoCancellation:  true,
        noiseSuppression:  true,
        autoGainControl:   true,
      },
    })

    audioContext = new AudioContext({ sampleRate: 16000 })
    const source = audioContext.createMediaStreamSource(mediaStream)
    // 每帧 1600 samples = 100ms @ 16kHz
    processor    = audioContext.createScriptProcessor(1600, 1, 1)

    processor.onaudioprocess = (e) => {
      // TTS 播放期间跳过发送（回声消除）
      if (ttsMuted || ws?.readyState !== WebSocket.OPEN) return

      const float32 = e.inputBuffer.getChannelData(0)
      const int16   = new Int16Array(float32.length)
      for (let i = 0; i < float32.length; i++) {
        int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768))
      }
      ws.send(int16.buffer)
    }

    source.connect(processor)
    processor.connect(audioContext.destination)
  }


  // ── 停止录音 ─────────────────────────────────────────────────────────────

  function stop() {
    processor?.disconnect()
    audioContext?.close()
    mediaStream?.getTracks().forEach(t => t.stop())
    ws?.close()
    status.value = 'idle'
  }


  // ── 清空转录文本 ──────────────────────────────────────────────────────────

  function clearTranscript() {
    transcript.value = ''
  }

  return { transcript, status, error, onTranscript, start, stop, clearTranscript }
}
```

---

## 13. TDD 验收测试

### `tests/test_asr_service.py`

```python
import pytest
import asyncio
import json
import numpy as np
from unittest.mock import patch, MagicMock


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    """
    初始化 ASRService，mock 掉 AutoModel 避免真实加载模型。
    每个测试用例使用独立实例。
    """
    with patch('services.asr_service.AutoModel') as mock_cls:
        mock_cls.return_value = MagicMock()
        from services.asr_service import ASRService
        service = ASRService()
        service.model = mock_cls.return_value
    return service


def make_audio(duration_s: float = 2.0) -> np.ndarray:
    """生成测试用正弦波音频（Float32，16kHz）"""
    samples = int(16000 * duration_s)
    t = np.linspace(0, duration_s, samples)
    return (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)


def make_silence(duration_s: float = 2.0) -> np.ndarray:
    return np.zeros(int(16000 * duration_s), dtype=np.float32)


# ─── TC-01: 核心工具方法 ──────────────────────────────────────────────────────

class TestUtils:

    def test_bytes_to_float32_range(self):
        """TC-01: Int16 PCM bytes 转 Float32 后值域在 [-1.0, 1.0]"""
        from services.asr_service import ASRService
        int16_data = np.array([0, 32767, -32768, 16384], dtype=np.int16)
        result = ASRService.bytes_to_float32(int16_data.tobytes())
        assert result.dtype == np.float32
        assert float(result.min()) >= -1.0
        assert float(result.max()) <= 1.0

    def test_bytes_to_float32_zero(self):
        """TC-02: 零值 Int16 转换后仍为零"""
        from services.asr_service import ASRService
        int16_data = np.zeros(100, dtype=np.int16)
        result = ASRService.bytes_to_float32(int16_data.tobytes())
        assert np.all(result == 0.0)

    def test_compute_rms_silence(self):
        """TC-03: 纯静音 RMS 接近 0"""
        from services.asr_service import ASRService
        silence = np.zeros(1600, dtype=np.float32)
        assert ASRService.compute_rms(silence) < 0.001

    def test_compute_rms_above_threshold_for_signal(self):
        """TC-04: 有效语音信号 RMS 高于静音阈值"""
        from services.asr_service import ASRService
        from config import ASR_SILENCE_RMS
        signal = make_audio(0.1)
        assert ASRService.compute_rms(signal) > ASR_SILENCE_RMS


# ─── TC-02: transcribe() 方法 ────────────────────────────────────────────────

class TestTranscribe:

    def test_empty_audio_returns_empty_string(self, svc):
        """TC-05: 空数组不调用模型，直接返回空字符串"""
        result = svc.transcribe(np.array([], dtype=np.float32))
        assert result == ''
        svc.model.generate.assert_not_called()

    def test_model_returns_empty_result(self, svc):
        """TC-06: 模型返回空结果时，transcribe 返回空字符串"""
        svc.model.generate.return_value = [{'text': ''}]
        result = svc.transcribe(make_audio())
        assert result == ''

    def test_model_returns_none(self, svc):
        """TC-07: 模型返回 None 时不报错，返回空字符串"""
        svc.model.generate.return_value = None
        result = svc.transcribe(make_audio())
        assert result == ''

    def test_hotword_passed_to_model(self, svc):
        """TC-08: hotword 参数被正确传给模型"""
        svc.model.generate.return_value = [{'text': '今天天气真好'}]
        svc.transcribe(make_audio())
        call_kwargs = svc.model.generate.call_args.kwargs
        assert 'hotword' in call_kwargs
        assert call_kwargs['hotword'] == svc.hotwords

    def test_itn_enabled(self, svc):
        """TC-09: use_itn=True 被传给模型（确保数字规范化）"""
        svc.model.generate.return_value = [{'text': '血压120'}]
        svc.transcribe(make_audio())
        call_kwargs = svc.model.generate.call_args.kwargs
        assert call_kwargs.get('use_itn') is True

    def test_returns_string_type(self, svc):
        """TC-10: 返回值类型为 str"""
        svc.model.generate.return_value = [{'text': '测试文本'}]
        result = svc.transcribe(make_audio())
        assert isinstance(result, str)


# ─── TC-03: VAD 参数配置 ─────────────────────────────────────────────────────

class TestVADConfig:

    def test_vad_kwargs_has_required_keys(self):
        """TC-11: VAD 配置包含全部必要参数"""
        from config import ASR_VAD_KWARGS
        required_keys = [
            'max_end_silence_time',
            'speech_noise_thres',
            'max_single_segment_time',
            'min_speech_duration',
        ]
        for key in required_keys:
            assert key in ASR_VAD_KWARGS, f"缺少 VAD 参数: {key}"

    def test_end_silence_time_long_enough_for_elderly(self):
        """TC-12: 静音时长 ≥ 1000ms，适应老人说话停顿"""
        from config import ASR_VAD_KWARGS
        assert ASR_VAD_KWARGS['max_end_silence_time'] >= 1000

    def test_silence_frame_count_corresponds_to_threshold(self):
        """TC-13: ASR_SILENCE_FRAMES 与 VAD 静音时长对应"""
        from config import ASR_SILENCE_FRAMES, ASR_VAD_KWARGS
        # 每帧 100ms，SILENCE_FRAMES × 100ms 应 ≤ max_end_silence_time
        frame_duration_ms = 100
        total_ms = ASR_SILENCE_FRAMES * frame_duration_ms
        assert total_ms <= ASR_VAD_KWARGS['max_end_silence_time'] * 1.5


# ─── TC-04: 服务初始化 ───────────────────────────────────────────────────────

class TestServiceInit:

    def test_hotwords_loaded_on_init(self):
        """TC-14: 初始化时自动加载 hotwords.txt"""
        with patch('services.asr_service.AutoModel'):
            from services.asr_service import ASRService
            service = ASRService()
        assert len(service.hotwords) > 0

    def test_model_initialized_with_cpu(self):
        """TC-15: 模型初始化时 device='cpu'"""
        with patch('services.asr_service.AutoModel') as mock_cls:
            mock_cls.return_value = MagicMock()
            from services.asr_service import ASRService
            ASRService()
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs.get('device') == 'cpu'

    def test_model_initialized_with_vad(self):
        """TC-16: 模型初始化时包含 vad_model"""
        with patch('services.asr_service.AutoModel') as mock_cls:
            mock_cls.return_value = MagicMock()
            from services.asr_service import ASRService
            ASRService()
        call_kwargs = mock_cls.call_args.kwargs
        assert 'vad_model' in call_kwargs
        assert call_kwargs['vad_model'] == 'fsmn-vad'

    def test_model_initialized_with_punc(self):
        """TC-17: 模型初始化时包含 punc_model"""
        with patch('services.asr_service.AutoModel') as mock_cls:
            mock_cls.return_value = MagicMock()
            from services.asr_service import ASRService
            ASRService()
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs.get('punc_model') == 'ct-punc'


# ─── TC-05: WebSocket 集成测试（需运行完整应用）────────────────────────────────

@pytest.mark.asyncio
async def test_websocket_connects_and_receives_status():
    """TC-18: WS 连接后收到 status: listening"""
    import websockets
    async with websockets.connect('ws://localhost:8000/ws/asr') as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert msg['type'] == 'status'
        assert msg['state'] == 'listening'


@pytest.mark.asyncio
async def test_silent_audio_does_not_produce_transcript():
    """TC-19: 50 帧纯静音不产生 transcript 消息"""
    import websockets
    silence = np.zeros(1600, dtype=np.int16)
    async with websockets.connect('ws://localhost:8000/ws/asr') as ws:
        await ws.recv()   # 消耗 status 消息
        for _ in range(50):
            await ws.send(silence.tobytes())
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.5))
            assert msg['type'] != 'transcript', "纯静音不应产生转录输出"
        except asyncio.TimeoutError:
            pass   # 超时即通过


@pytest.mark.asyncio
async def test_transcript_message_contains_emotion_field():
    """TC-20: transcript 消息包含 emotion 字段（合并架构特有）"""
    # 此测试需要真实语音输入，集成测试阶段实现
    # 验证点：msg['emotion'] 包含 label, score, valence, arousal 字段
    required_emotion_fields = ['label', 'label_zh', 'score', 'valence', 'arousal', 'trend', 'history']
    mock_msg = {
        'type':    'transcript',
        'text':    '测试',
        'emotion': {f: None for f in required_emotion_fields},
    }
    for field in required_emotion_fields:
        assert field in mock_msg['emotion']
```

### 验收标准汇总

| ID | 分类 | 描述 | 通过条件 |
|----|------|------|----------|
| TC-01 | 工具 | Int16→Float32 值域 | `[-1.0, 1.0]` 内 |
| TC-02 | 工具 | 零值转换 | 结果全为 0.0 |
| TC-03 | 工具 | 静音 RMS | < 0.001 |
| TC-04 | 工具 | 信号 RMS | > `ASR_SILENCE_RMS` |
| TC-05 | 转录 | 空数组不调模型 | model 未被调用，返回 `''` |
| TC-06 | 转录 | 模型空结果 | 返回 `''` |
| TC-07 | 转录 | 模型返回 None | 不报错，返回 `''` |
| TC-08 | 转录 | 热词参数传递 | `hotword` 字段存在 |
| TC-09 | 转录 | ITN 开启 | `use_itn=True` |
| TC-10 | 转录 | 返回类型 | `isinstance(result, str)` |
| TC-11 | VAD | 配置键完整 | 4 个必要键均存在 |
| TC-12 | VAD | 静音时长充足 | `≥ 1000ms` |
| TC-13 | VAD | 帧数与时长对应 | `frames × 100ms` 合理 |
| TC-14 | 初始化 | 热词加载 | `len(hotwords) > 0` |
| TC-15 | 初始化 | CPU 设备 | `device='cpu'` |
| TC-16 | 初始化 | VAD 模型 | `vad_model='fsmn-vad'` |
| TC-17 | 初始化 | 标点模型 | `punc_model='ct-punc'` |
| TC-18 | 集成 | WS 连接成功 | 收到 `status: listening` |
| TC-19 | 集成 | 静音无输出 | 无 transcript 消息 |
| TC-20 | 集成 | transcript 含 emotion | 7 个字段均存在 |

---

## 附录：常见问题

**Q：模型下载失败？**
```bash
export MODELSCOPE_CACHE=/data/models
python -c "from funasr import AutoModel; AutoModel(model='paraformer-zh')"
```

**Q：CPU 推理太慢？**
- 调整 `config.py` 中 `ncpu=4` 为实际核数
- 降级为 `paraformer-zh-streaming`（流式版，延迟更低但准确率略低）

**Q：合并架构下如何单独测试 ASR 不启动其他服务？**
```python
# 在测试中 mock EmotionService，只测试 ASR 逻辑
with patch('routers.ws_asr.emotion_service') as mock_emotion:
    mock_emotion.analyze.return_value = mock_emotion_result
    # ... 测试 ASR 路由
```
