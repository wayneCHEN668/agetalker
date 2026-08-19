# 原生端音频管线（录音 / 放音）— 设计文档

- 日期：2026-08-19
- 状态：设计已确认，待写实现计划
- 影响范围：`mobile/` 前端，不涉及后端
- 目标平台：Android（现场测试目标）；iOS 兼容性为加分项，非硬指标

---

## 1. 背景

APK 装到设备上之后无法正常工作。排查下来是两个层次的问题：

**表层**：`useASR.ts` / `useTTS.ts` 用 `window.addEventListener` / `window.dispatchEvent`
做 TTS 静音信号的收发，原生运行时里 `window` 没有 DOM 的这两个方法，一进页面
就抛 `window.addEventListener is not a function`。这一处已先行修掉（改用 RN 内建的
`DeviceEventEmitter`），应用不再启动即崩。

**根因**：录音与放音**整条链路建立在浏览器 Web Audio / WebRTC API 之上**，
原生运行时里这些 API 根本不存在：

| 位置 | 依赖的 Web API |
|---|---|
| `useASR.ts:157` | `navigator.mediaDevices.getUserMedia` |
| `useASR.ts:166` | `new AudioContext({sampleRate:16000})` |
| `useASR.ts:177` | `createScriptProcessor`（逐帧回调） |
| `useTTS.ts:48` | `window.AudioContext` |
| `useTTS.ts:107-116` | `createBuffer` / `createBufferSource` / `source.start(when)` |

`useASR.ts:99-102` 有一道显式拦截：

```js
if (Platform.OS !== 'web') {
  console.warn('Real-time audio capture is currently optimized for Web/Laptop testing.');
  return;
}
```

即原生端按下「我想和你聊聊」只是静默返回，什么都不会发生。**这是一直待办的
工作，不是回归。**

## 2. 目标与非目标

### 目标

- Android 端能完整走通：录音 → WebSocket 上行 → 收到回复 → 播放 TTS
- **完整复制现有 web 端行为**，包括：
  - 逐帧 RMS 自适应打断检测（底噪采样 → 算阈值 → 连续帧判定 → 补发预缓冲）
  - 打断时按实际播放进度精确截断对话历史（`getSpokenText`）
- web 端不退步

### 非目标

- iOS 真机验证（无 Mac，本轮不做）
- 音质优化、降噪调参（超出「跑通 + 复制行为」的范围）
- 后端任何改动

## 3. 方案选型

### 选定：`react-native-audio-api`（Software Mansion）

核心理由：**它的 API 就是 Web Audio API 规范的实现**，与现有代码几乎一一对应，
意味着已经调好的打断检测与精确截断逻辑大部分是「换个 import 来源」而非重新设计，
复制行为的风险最低。

已核实的关键事实：

- `AudioRecorder.onAudioReady({sampleRate, bufferLength, channelCount}, cb)`
  提供原始 PCM 帧回调，样本为 -1.0~1.0 浮点 —— 与现有 `getChannelData(0)` 格式一致
- `AudioContext` / `createBuffer` / `createBufferSource` / `start(when)` / `currentTime`
  签名语义与浏览器一致
- `AnalyserNode` 完整支持，含本项目用到的 `getByteTimeDomainData` /
  `getByteFrequencyData` / `frequencyBinCount` / `fftSize` / `smoothingTimeConstant`
- 支持 RN 0.81（本项目版本）与 New Architecture（本项目 `newArchEnabled: true`）
- 提供 Expo config plugin，契合本项目已在用的 prebuild 流程
- **web 端同样可用**：官方文档明确「在 web 上库会转而使用浏览器内建的
  Web Audio API」

### 落选方案

**B. 纯 PCM 流库**（如 `react-native-audio-pcm-stream`）：只解决录音侧帧回调，
放音侧缺少精确调度能力，`scheduleRef` 那套「记录每段精确播放时间窗、瞬间截断」
需要自行在原生层重建，工作量与风险都更大。

**C. 自写原生模块**（Kotlin 包 `AudioRecord`/`AudioTrack`）：完全可控，但属于
重复造轮子，方案 A 已提供同等能力且为活跃维护的成熟库。

## 4. 架构决策

### 4.1 两端统一，而非「给原生加一条分支」

因为 `react-native-audio-api` 在 web 上也能跑，**web 与原生走同一套 API**，
`useASR.ts:99-102` 的 `Platform.OS !== 'web'` 拦截**直接删除**。

- **代价**：web 端也跟着换库，现有 web 行为有回归风险，需完整重测
- **收益**：长期只维护一套逻辑。若走「加原生分支」，两条路径会各自演化，
  web 上调好的打断参数在原生上对不上，最终要调两遍、且永远无法确认两边一致

这是本设计中最重要的一个取舍。

### 4.2 对外接口保持不变

`useASR` / `useTTS` 的返回签名与语义完全不变，`index.tsx` **一行都不用改**：

```
useASR  → { start, stop, status, isRecording, analyser }
useTTS  → { speak, stop, stopForBargeIn, getSpokenText, resetSpokenText,
            isPlaying, isPlayingRef }
```

只替换 hook 内部的音频后端实现。

### 4.3 帧参数精确对齐后端

后端 `config.py` 约定：`ASR_SAMPLE_RATE = 16000`，`ASR_FRAME_SAMPLES = 2048`
（约 128ms/帧）。因此 `onAudioReady` 配置为：

```js
{ sampleRate: 16000, bufferLength: 2048, channelCount: 1 }
```

`BargeIn` 常量里所有「每帧约 128ms」的推算（`SUSTAINED_FRAMES: 3` ≈ 380ms、
`PREBUFFER_FRAMES: 6`）因此继续成立，无需换算。

## 5. 数据流

### 5.1 录音侧（`useASR.ts`）

```
AudioRecorder.onAudioReady(16kHz / 2048 / mono)
  → Float32 帧
  → 转 Int16                              [现有代码不变]
  → isTTSMutedRef?
      ├─ false → WebSocket.send(pcm)      [现有代码不变]
      └─ true  → 存入 preBuffer（上限 PREBUFFER_FRAMES）
                 + RMS 打断检测            [现有代码不变]
                   ├─ elapsed < BASELINE_MS  → 采底噪
                   ├─ threshold 未算 → 由底噪 × THRESHOLD_RATIO 算出
                   ├─ elapsed < GRACE_MS     → 不判打断
                   └─ 连续 SUSTAINED_FRAMES 帧超阈值
                        → 解除静音 + 补发 preBuffer + onBargeIn()
  → 同时 audioRecorder.connect(ctx, analyser) 供 Waveform / Orb
```

打断检测的**全部逻辑一行不改**，仅数据来源从 `e.inputBuffer.getChannelData(0)`
变为 `onAudioReady` 回调的 `buffer`。

### 5.2 放音侧（`useTTS.ts`）

`fetchAndSchedule` / `scheduleRef` / `getSpokenText` / `haltAudio` **全部不改**，
仅 `AudioContext` 的 import 来源变化。依赖的 API 均已确认对等：

| 用途 | API |
|---|---|
| 建 context | `new AudioContext({sampleRate: 24000})` |
| 建缓冲 | `ctx.createBuffer(1, len, 24000)` |
| 排期播放 | `src.start(startTime)` |
| 查询进度（精确截断的基础） | `ctx.currentTime` |
| 急停 | `src.stop()` |

### 5.3 新增生命周期（web 端没有的）

1. **权限**：`AudioManager.requestRecordingPermissions()`，返回值不是 `'Granted'`
   时走 `onError` 提示，文案面向老人（如「我听不见您说话，请在设置里允许使用
   麦克风」），不是 `console.warn`
2. **音频会话**：`start()` 时 `AudioManager.setAudioSessionActivity(true)`，
   `stop()` 时 `false`
3. **配置**：`app.json` 增加 `react-native-audio-api` 的 Expo plugin，声明
   `android.permission.RECORD_AUDIO`

## 6. 错误处理

三处新增失败路径，全部复用现有 `onError` 回调链与 `ErrorToast` 组件：

| 失败点 | 处理 |
|---|---|
| 权限被拒 | 提示去设置里开麦克风权限，不重试 |
| `audioRecorder.start()` 返回 `status === 'error'` | 提示重试一次 |
| `setAudioSessionActivity` 抛错 | 提示重试一次 |

原则与现有代码一致：**面向老人的文案，不暴露技术细节**。

## 7. 验证方式

诚实说明：`mobile/` 目前只有 `jest-expo` 跑纯逻辑测试，音频链路**无法自动化
测试**（需要真实麦克风与扬声器）。因此验证分三层：

### 7.1 可自动化（每次改动都跑）

- `npx tsc --noEmit` 无错
- `npm test` 现有 jest 测试不回归

### 7.2 web 端手动回归（换库的主要风险所在）

`npx expo start --web`，逐项确认：

- [ ] 按「我想和你聊聊」能开始录音，说话出字
- [ ] AI 回复能出声，多句之间无卡顿
- [ ] AI 说话时插话，能打断，且屏幕文字截断在实际听到的位置
- [ ] 「结束对话」能播完告别再清屏
- [ ] Waveform / Orb 随声音起伏

### 7.3 Android 手动验证

模拟器或真机（真机优先，模拟器麦克风行为不可靠）：

- [ ] 首次启动弹出麦克风权限申请
- [ ] 拒绝权限时给出可读提示，不崩
- [ ] 录音出字
- [ ] TTS 出声
- [ ] 插话能打断
- [ ] 结束对话流程完整

实现完成后会给出一份具体的手测清单，而不是笼统的「测一下」。

## 8. 未解决的问题 / 风险

### 8.1 Android 回声消除（AEC）无着落 —— 最高风险

**当前设计按「Android 存在可用 AEC」的乐观假设推进，此假设未经验证。**

已知证据：

- 该库 README 的 Roadmap 中，「Noise Cancellation for active noise and echo
  reduction」列在 **Planned（计划中）**，即尚未实现
- `SessionOptions` 中与 AEC 相关的配置**只有 iOS 项**（`iosMode: 'voiceChat'`
  等会触发 iOS 系统 AEC），无 Android 对应项
- `AudioRecorder` 可配置项仅 `sampleRate` / `bufferLength` / `channelCount`，
  无 `echoCancellation`

未知部分：Android 底层若内部采用 `MediaRecorder.AudioSource.VOICE_COMMUNICATION`
作为采集源，系统会自动挂载硬件 AEC；若用 `MIC` 或 `DEFAULT` 则没有。文档未说明，
需实测或读源码确认。

**为何是卡点**：打断检测的整个阈值模型建立在「AEC 已消掉喇叭声，收到的基本是
房间本底」这一前提上（见 `constants/BargeIn.ts` 顶部注释）。若 Android 无 AEC，
TTS 一放音，麦克风收到的即是自己的喇叭声，`baselineRms` 与 `threshold` 被显著
抬高，连续超阈值判定会持续触发 —— 表现为 **AI 刚开口就把自己掐断，反复循环**。
这不是精度问题，是功能不可用。

**若实现阶段证实无 AEC，可选的补偿路径**（届时需重新讨论，可能改变设计）：

- 自研简易回声抑制（用已知的 TTS 输出信号做参考做谱减）
- 改用混合判据：TTS 播放期间大幅提高阈值 + 依赖 ASR 侧返回的文本做二次确认
- 降级：关闭 `BARGE_IN.ENABLED`，退回「不能打断」的老行为（现有常量已预留此开关）

### 8.2 双 AudioContext 采样率

web 端现状是**两个不同采样率的 AudioContext 并存**：ASR 侧 16kHz、TTS 侧 24kHz
（`TTS_SAMPLE_RATE = 24000`，CosyVoice 输出）。原生端能否同时开两个不同采样率的
context，文档未明确说明。

若不支持，退路是统一到单一采样率，在 TTS 侧对 24kHz 数据做重采样后播放。

### 8.3 web 端回归风险

4.1 的「两端统一」决策意味着 web 端也换了音频后端。虽然该库在 web 上转调浏览器
原生 Web Audio API，理论上行为一致，但**必须按 7.2 完整重测**，尤其是打断检测的
阈值表现 —— 这部分参数原本是对着浏览器 AEC 的行为调出来的。

## 9. 影响的文件

| 文件 | 改动 |
|---|---|
| `mobile/hooks/useASR.ts` | 替换音频采集后端；删除 `Platform.OS` 拦截；新增权限与会话生命周期 |
| `mobile/hooks/useTTS.ts` | 替换 `AudioContext` import 来源；新增会话生命周期 |
| `mobile/app.json` | 新增 `react-native-audio-api` Expo plugin 配置 |
| `mobile/package.json` | 新增依赖 |
| `mobile/constants/BargeIn.ts` | 可能微调阈值（取决于实测） |

`mobile/app/(tabs)/index.tsx`、`components/Waveform.tsx`、`components/OrbVisualizer.tsx`
**不改** —— hook 对外接口保持不变，Orb 原生降级路径已存在。
