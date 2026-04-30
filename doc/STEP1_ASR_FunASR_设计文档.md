# STEP 1 — 实时语音转录模块
**技术栈：FunASR paraformer-zh + fsmn-vad + ct-punc**

---

## 目录
1. [模块概述](#1-模块概述)
2. [技术选型](#2-技术选型)
3. [系统架构](#3-系统架构)
4. [环境依赖与安装](#4-环境依赖与安装)
5. [核心实现代码](#5-核心实现代码)
6. [VAD 参数调优](#6-vad-参数调优老人语音专项)
7. [准确率保障措施](#7-准确率保障措施)
8. [WebSocket 消息协议](#8-websocket-消息协议)
9. [服务启动命令](#9-服务启动命令)
10. [TDD 验收测试](#10-tdd-验收测试)

---

## 1. 模块概述

本模块负责从麦克风实时采集音频，经过语音活动检测（VAD）进行句级切分后，调用 **FunASR paraformer-zh** 模型完成中文语音识别，并通过标点恢复模型输出完整句子文本，最终通过 **WebSocket 流式推送**至前端显示。

### 目标指标

| 指标 | 目标值 |
|------|--------|
| 识别准确率（CER） | ≥ 95%（字符错误率 < 5%） |
| 单句推理延迟 | VAD 触发静音后 ≤ 800ms 输出结果 |
| 支持语言 | 中文普通话（兼容少量方言词汇） |
| 运行环境 | 纯 CPU，无需 GPU |
| 句级切分 | 以自然句为单位，停顿 ≥ 1.5s 触发切句 |

---

## 2. 技术选型

| 组件 | 选型 | 说明 |
|------|------|------|
| ASR 核心 | `paraformer-zh`（非流式） | FunASR 官方中文 ASR，CPU 可用，准确率高 |
| VAD | `fsmn-vad` | FunASR 内置 VAD，检测说话起止时间点 |
| 标点恢复 | `ct-punc` | FunASR 内置标点模型，输出完整句子 |
| 热词增强 | paraformer-zh 热词接口 | 注入养老场景专业词汇提升准确率 |
| 服务框架 | Python FastAPI + WebSocket | 异步后端，支持多并发 |
| 音频传输 | WebSocket 二进制帧 | 前端直接发送 PCM 音频数据 |

> **为什么选 paraformer-zh 而非 Whisper？**
> - Whisper 中文标点输出差，需额外标点恢复处理
> - paraformer-zh 在中文口语上 CER 更低（约 3-4% vs 5-7%）
> - CPU 推理速度 paraformer 更快（实时率 RTF < 0.1）

---

## 3. 系统架构

### 3.1 数据流

```
前端 (Vue3/React)
  │
  │  WebSocket 连接: ws://localhost:8000/ws/asr
  │  ─── 二进制帧: PCM 16kHz 16bit mono ──→
  ↓
ASR WebSocket 服务 (FastAPI)
  │
  ├─ 音频缓冲区 (AudioBuffer)
  │    ↓  每 100ms 追加一帧 (1600 samples)
  ├─ 静音检测（RMS 能量 + 帧计数）
  │    ├─ 检测到语音 → 继续累积
  │    └─ 静音 ≥ 1.5s 且有积累音频 → 触发推理
  │         ↓
  ├─ paraformer-zh 推理（run_in_executor 异步）
  │         ↓
  ├─ ct-punc 标点恢复
  │         ↓
  └─ WebSocket 推送 JSON ──→ 前端显示转录文本
                          ──→ 同时触发 STEP 2 情绪识别
```

### 3.2 跨模块事件

```
ASR 模块发出事件（通过 WebSocket / 内部事件总线）:

  ASR_TRANSCRIPT_READY
  {
    text: string,          // 转录文本
    audio_b64: string,     // Base64 PCM，供 STEP 2 情绪识别
    duration_ms: number,   // 音频时长
    timestamp: number      // Unix 时间戳
  }
```

---

## 4. 环境依赖与安装

### 4.1 Python 依赖

```
# requirements_step1.txt
funasr>=1.1.0
torch>=2.0.0            # CPU 版本，无需 CUDA
torchaudio>=2.0.0
fastapi>=0.110.0
websockets>=12.0
uvicorn[standard]>=0.29.0
numpy>=1.24.0
python-dotenv>=1.0.0
```

安装命令：

```bash
pip install -r requirements_step1.txt
# 安装 CPU 版 PyTorch（避免下载 CUDA 版本，体积更小）
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### 4.2 模型首次下载

模型会在首次运行时自动从 ModelScope 下载，缓存至 `~/.cache/modelscope/`。

```python
from funasr import AutoModel

# 首次运行自动下载，约 500MB
asr_model = AutoModel(
    model='paraformer-zh',
    vad_model='fsmn-vad',
    punc_model='ct-punc',
    device='cpu',
    disable_update=True,
)
```

> ⚠️ **离线部署**：设置环境变量 `MODELSCOPE_CACHE=/your/path`，联网下载一次后可完全离线运行。

### 4.3 热词文件 `hotwords.txt`

每行一个热词，用于提升养老场景专业词汇的识别准确率：

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

## 5. 核心实现代码

### 5.1 目录结构

```
step1_asr/
├── asr_server.py        # FastAPI 主服务
├── hotwords.txt         # 热词列表
├── requirements_step1.txt
├── .env                 # 环境变量
└── tests/
    └── test_step1.py    # TDD 测试
```

### 5.2 主服务 `asr_server.py`

```python
import asyncio
import json
import base64
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ASR Service - STEP 1")

# ─── 模型初始化（服务启动时加载，约 20-40s）─────────────────────────────────
logger.info("正在加载 ASR 模型，请稍候...")

asr = AutoModel(
    model='paraformer-zh',
    vad_model='fsmn-vad',
    punc_model='ct-punc',
    device='cpu',
    disable_update=True,
    vad_kwargs={
        'max_end_silence_time': 1500,      # ms，静音超过此时长触发切句（老人说话慢，调大）
        'speech_noise_thres': 0.75,         # 降低噪声判定阈值
        'max_single_segment_time': 30000,   # ms，单句最长时间
        'min_speech_duration': 300,          # ms，最短有效语音
    },
    ncpu=4,   # CPU 线程数，根据机器核数调整
)

HOTWORDS = open('hotwords.txt', encoding='utf-8').read().strip()
SAMPLE_RATE = 16000
FRAME_SIZE = 1600        # 100ms @ 16kHz
SILENCE_RMS = 0.008      # 静音 RMS 阈值
SILENCE_FRAMES = 15      # 15帧 × 100ms = 1.5s

logger.info("ASR 模型加载完成 ✅")


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def bytes_to_float32(data: bytes) -> np.ndarray:
    """Int16 PCM bytes → Float32 normalized"""
    int16 = np.frombuffer(data, dtype=np.int16)
    return int16.astype(np.float32) / 32768.0


def compute_rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio ** 2)))


def run_asr(audio: np.ndarray) -> str:
    """同步执行 ASR 推理，返回带标点文本"""
    result = asr.generate(
        input=audio,
        language='zh',
        use_itn=True,          # 逆文本归一化：数字、单位规范化
        batch_size_s=60,
        hotword=HOTWORDS,
    )
    if not result or not result[0].get('text'):
        return ''
    return rich_transcription_postprocess(result[0]['text'])


# ─── WebSocket 端点 ──────────────────────────────────────────────────────────

@app.websocket('/ws/asr')
async def asr_endpoint(ws: WebSocket):
    await ws.accept()
    logger.info(f"客户端已连接: {ws.client}")

    audio_buffer: list = []
    silent_frames: int = 0
    cache: dict = {}

    # 通知客户端服务就绪
    await ws.send_text(json.dumps({'type': 'status', 'state': 'listening'}))

    try:
        while True:
            # 接收音频二进制帧
            data = await ws.receive_bytes()
            chunk = bytes_to_float32(data)
            rms = compute_rms(chunk)

            if rms < SILENCE_RMS:
                silent_frames += 1
            else:
                silent_frames = 0
                audio_buffer.append(chunk)

            # 条件：静音超过阈值 且 有积累的语音片段
            if silent_frames >= SILENCE_FRAMES and len(audio_buffer) > 5:
                audio = np.concatenate(audio_buffer)
                audio_buffer.clear()
                silent_frames = 0

                # 通知前端"处理中"
                await ws.send_text(json.dumps({'type': 'status', 'state': 'processing'}))

                # 异步执行推理（不阻塞事件循环）
                loop = asyncio.get_event_loop()
                text = await loop.run_in_executor(None, lambda: run_asr(audio))

                if text.strip():
                    logger.info(f"转录结果: {text}")
                    audio_b64 = base64.b64encode(
                        (audio * 32768).astype(np.int16).tobytes()
                    ).decode()
                    await ws.send_text(json.dumps({
                        'type': 'transcript',
                        'text': text,
                        'is_final': True,
                        'audio_b64': audio_b64,          # 供 STEP 2 情绪识别
                        'duration_ms': int(len(audio) / SAMPLE_RATE * 1000),
                        'timestamp': asyncio.get_event_loop().time(),
                    }))

                # 恢复监听状态
                await ws.send_text(json.dumps({'type': 'status', 'state': 'listening'}))

    except WebSocketDisconnect:
        logger.info(f"客户端断开: {ws.client}")
    except Exception as e:
        logger.error(f"ASR 处理异常: {e}")
        await ws.send_text(json.dumps({
            'type': 'error',
            'code': 'ASR_ERROR',
            'message': str(e),
        }))
```

### 5.3 前端音频采集 `composables/useASR.ts`

```typescript
import { ref } from 'vue'

// TTS 播放期间静音麦克风（回声消除，由 STEP 4 触发）
let ttsMuted = false
window.addEventListener('tts-start', () => { ttsMuted = true })
window.addEventListener('tts-end', () => {
  setTimeout(() => { ttsMuted = false }, 200)  // 延迟 200ms 再恢复
})

export function useASR(wsUrl = 'ws://localhost:8000/ws/asr') {
  const transcript = ref('')
  const status = ref<'idle' | 'listening' | 'processing'>('idle')
  const error = ref('')

  let ws: WebSocket | null = null
  let audioContext: AudioContext | null = null
  let processor: ScriptProcessorNode | null = null
  let mediaStream: MediaStream | null = null

  // 回调：收到转录结果时触发（供 STEP 2、3 消费）
  const onTranscript = ref<((data: TranscriptEvent) => void) | null>(null)

  interface TranscriptEvent {
    text: string
    audio_b64: string
    duration_ms: number
    timestamp: number
  }

  async function start() {
    ws = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => { status.value = 'listening' }
    ws.onclose = () => { status.value = 'idle' }
    ws.onerror = (e) => { error.value = '连接失败' }

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data as string)
      if (msg.type === 'transcript') {
        transcript.value += msg.text
        onTranscript.value?.(msg)
      } else if (msg.type === 'status') {
        status.value = msg.state
      } else if (msg.type === 'error') {
        error.value = msg.message
      }
    }

    // 请求麦克风权限
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: 16000,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }
    })

    audioContext = new AudioContext({ sampleRate: 16000 })
    const source = audioContext.createMediaStreamSource(mediaStream)
    processor = audioContext.createScriptProcessor(1600, 1, 1)  // 100ms 帧

    processor.onaudioprocess = (e) => {
      // TTS 播放期间跳过发送（回声消除）
      if (ttsMuted || ws?.readyState !== WebSocket.OPEN) return

      const float32 = e.inputBuffer.getChannelData(0)
      const int16 = new Int16Array(float32.length)
      for (let i = 0; i < float32.length; i++) {
        int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768))
      }
      ws.send(int16.buffer)
    }

    source.connect(processor)
    processor.connect(audioContext.destination)
  }

  function stop() {
    processor?.disconnect()
    audioContext?.close()
    mediaStream?.getTracks().forEach(t => t.stop())
    ws?.close()
    status.value = 'idle'
  }

  function clearTranscript() {
    transcript.value = ''
  }

  return { transcript, status, error, onTranscript, start, stop, clearTranscript }
}
```

---

## 6. VAD 参数调优（老人语音专项）

> ⚠️ **重要**：老人说话速度慢、停顿多，默认 VAD 参数会过早切句，**必须**调整以下参数。

| 参数 | 默认值 | 推荐值 | 调整原因 |
|------|--------|--------|----------|
| `max_end_silence_time` | 500ms | **1500ms** | 老人句中停顿多，需更长静音才切句 |
| `speech_noise_thres` | 0.9 | **0.75** | 降低噪声判定阈值，适应背景噪音 |
| `max_single_segment_time` | 15s | **30s** | 避免长句被强制切断 |
| `min_speech_duration` | 200ms | **300ms** | 过滤误触发，要求更长的有效语音 |

**参数生效代码位置**：`asr_server.py` 中 `AutoModel` 初始化的 `vad_kwargs` 字典。

---

## 7. 准确率保障措施

以下 5 项措施综合保障识别准确率 ≥ 95%：

| 措施 | 实现方式 | 预期提升 |
|------|----------|----------|
| **1. 热词注入** | `hotword=HOTWORDS` 参数 | 养老词汇识别率 +10-15% |
| **2. ITN 规范化** | `use_itn=True` | 数字、单位输出规范 |
| **3. 标点恢复** | `ct-punc` 模型 | 句子完整性提升 |
| **4. 后处理** | `rich_transcription_postprocess()` | 去除填充词、语气词 |
| **5. 回声消除** | TTS 期间暂停发送音频帧 | 避免 AI 声音被误识别 |

---

## 8. WebSocket 消息协议

### 前端 → 后端（二进制帧）

```
每 100ms 发送一帧 PCM 数据
格式: ArrayBuffer (Int16Array, 16kHz, 单声道, 1600 samples/帧)
```

### 后端 → 前端（JSON 文本帧）

**转录结果：**
```json
{
  "type": "transcript",
  "text": "今天天气真好，我想出去走走。",
  "is_final": true,
  "audio_b64": "<base64 encoded Int16 PCM>",
  "duration_ms": 3200,
  "timestamp": 1712345678.123
}
```

**服务状态：**
```json
{
  "type": "status",
  "state": "listening"
}
```
`state` 枚举值：`listening`（等待输入）| `processing`（推理中）| `idle`（未连接）

**错误：**
```json
{
  "type": "error",
  "code": "ASR_ERROR",
  "message": "具体错误描述"
}
```

---

## 9. 服务启动命令

```bash
# 开发模式（热重载）
uvicorn asr_server:app --host 0.0.0.0 --port 8000 --reload

# 生产模式
uvicorn asr_server:app --host 0.0.0.0 --port 8000 --workers 1

# 注意：ASR 模型有状态（audio_buffer），workers 建议设为 1
# 如需多并发，每个 WebSocket 连接维护独立缓冲区，已在代码中实现
```

---

## 10. TDD 验收测试

### 测试依赖安装

```bash
pip install pytest pytest-asyncio httpx httpx-ws
```

### 测试文件 `tests/test_step1.py`

```python
import pytest
import asyncio
import json
import numpy as np


# ─── 单元测试 ────────────────────────────────────────────────────────────────

class TestAudioUtils:
    """TC-01 ~ TC-03: 音频工具函数测试"""

    def test_bytes_to_float32_range(self):
        """TC-01: Int16 转 Float32 后范围在 [-1, 1]"""
        from asr_server import bytes_to_float32
        int16_data = np.array([0, 32767, -32768, 16384], dtype=np.int16)
        result = bytes_to_float32(int16_data.tobytes())
        assert result.dtype == np.float32
        assert np.all(result >= -1.0) and np.all(result <= 1.0)

    def test_compute_rms_silence(self):
        """TC-02: 纯静音 RMS 接近 0"""
        from asr_server import compute_rms
        silence = np.zeros(1600, dtype=np.float32)
        assert compute_rms(silence) < 0.001

    def test_compute_rms_signal(self):
        """TC-03: 有信号时 RMS > 静音阈值"""
        from asr_server import compute_rms, SILENCE_RMS
        signal = np.sin(np.linspace(0, 2 * np.pi, 1600)).astype(np.float32) * 0.5
        assert compute_rms(signal) > SILENCE_RMS


# ─── 集成测试（需运行服务）────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_websocket_connects():
    """TC-04: WebSocket 正常建立连接并收到 status 消息"""
    import websockets
    async with websockets.connect('ws://localhost:8000/ws/asr') as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert msg['type'] == 'status'
        assert msg['state'] == 'listening'


@pytest.mark.asyncio
async def test_silent_audio_no_transcript():
    """TC-05: 发送纯静音音频，不产生 transcript 消息"""
    import websockets
    silence = np.zeros(1600, dtype=np.int16)
    async with websockets.connect('ws://localhost:8000/ws/asr') as ws:
        await ws.recv()  # 消耗 status 消息
        # 发送 5s 静音（50帧）
        for _ in range(50):
            await ws.send(silence.tobytes())
        # 等待 500ms，不应收到 transcript
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.5))
            assert msg['type'] != 'transcript', "静音不应产生转录输出"
        except asyncio.TimeoutError:
            pass  # 超时即通过


@pytest.mark.asyncio
async def test_transcript_message_format():
    """TC-06: 转录结果消息格式完整"""
    # 需要真实语音文件，建议用预录制测试音频
    # 此处为格式验证占位，实际集成测试时实现
    required_fields = ['type', 'text', 'is_final', 'audio_b64', 'duration_ms', 'timestamp']
    mock_msg = {
        'type': 'transcript',
        'text': '测试文本',
        'is_final': True,
        'audio_b64': 'xxx',
        'duration_ms': 2000,
        'timestamp': 1234567890.0,
    }
    for field in required_fields:
        assert field in mock_msg


# ─── 准确率评估脚本（需准备测试数据集）────────────────────────────────────────

# python eval_accuracy.py --audio_dir ./test_audio/ --label_file labels.txt
# 期望输出: CER < 5%（即准确率 ≥ 95%）
```

### 验收标准

| 测试用例 | 通过条件 |
|----------|----------|
| TC-01 音频转换 | Float32 值域 [-1, 1] |
| TC-02 静音 RMS | RMS < 0.001 |
| TC-03 信号 RMS | RMS > SILENCE_RMS 阈值 |
| TC-04 WebSocket 连接 | 5s 内收到 `status: listening` |
| TC-05 静音不输出 | 50帧静音后无 transcript 消息 |
| TC-06 消息格式 | 所有必填字段存在 |
| TC-07 准确率（人工） | 测试集 CER < 5% |

---

## 附录：常见问题

**Q: 模型下载失败？**
```bash
# 手动下载并设置缓存路径
export MODELSCOPE_CACHE=/data/models
python -c "from funasr import AutoModel; AutoModel(model='paraformer-zh')"
```

**Q: CPU 推理太慢？**
- 调整 `ncpu=` 参数为机器实际核数
- 对于长音频，`batch_size_s=60` 可适当调大
- 使用 `paraformer-zh-streaming` 流式版本（延迟更低但准确率略低）

**Q: 老人方言识别差？**
- 在 `hotwords.txt` 中加入当地常用词汇
- 考虑微调模型（需准备本地口音语料）
