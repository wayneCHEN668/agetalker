# 原生端音频管线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Android 端能完整走通「录音 → 上行 → 收到回复 → 播放 TTS」，并完整保留 web 端已有的逐帧打断检测与精确历史截断行为。

**Architecture:** 用 `react-native-audio-api`（Web Audio API 规范的 RN 实现）替换 `useASR`/`useTTS` 内部的浏览器音频后端。因该库在 web 上转调浏览器原生 Web Audio API，**web 与原生走同一套 API**，删除 `useASR.ts` 里的 `Platform.OS !== 'web'` 拦截，不引入平台分支。两个 hook 的对外接口完全不变，`index.tsx` 不改。

**Tech Stack:** React Native 0.81 / Expo SDK 54 / New Architecture / `react-native-audio-api` / TypeScript / jest-expo

**Spec:** `docs/superpowers/specs/2026-08-19-native-audio-pipeline-design.md`

## Global Constraints

- 目标平台：**Android**。iOS 本轮不做真机验证（无 Mac），但不得写入 Android-only 的代码分支。
- ASR 帧参数必须与后端 `backend/config.py` 严格一致：`ASR_SAMPLE_RATE = 16000`、`ASR_FRAME_SAMPLES = 2048`（约 128ms/帧）。**改动此值会使 `constants/BargeIn.ts` 里所有基于「每帧约 128ms」的推算失效。**
- TTS 采样率固定 `24000`（CosyVoice 输出，见 `backend/config.py:300`）。
- `useASR` 对外返回签名不变：`{ start, stop, status, isRecording, analyser }`。
- `useTTS` 对外返回签名不变：`{ speak, stop, stopForBargeIn, getSpokenText, resetSpokenText, isPlaying, isPlayingRef }`。
- `mobile/app/(tabs)/index.tsx`、`components/Waveform.tsx`、`components/OrbVisualizer.tsx` **不得修改**。
  **例外（Task 4 实现期间发现，见 spec §4.1a）**：`useASR` 返回的 `analyser` 类型从 DOM 全局
  `AnalyserNode` 变成库自带的 `AnalyserNode` 类后，tsc 会在这两个文件报结构不匹配。允许对
  `Waveform.tsx`/`OrbVisualizer.tsx` 做**仅类型导入**的修改（`import type { AnalyserNode } from
  'react-native-audio-api'`，替换掉隐式的 DOM 全局类型），前提是不改变任何运行时行为——
  这两个文件只调用 `frequencyBinCount`/`getByteTimeDomainData`/`getByteFrequencyData`/`fftSize`/
  `smoothingTimeConstant`，库的 `AnalyserNode` 对这些成员的实现与 DOM 版一致。除类型导入行以外
  不得有任何其他改动。
- 面向老人的错误文案：不暴露技术细节，不出现英文与错误码。
- 每个任务结束时 `npx tsc --noEmit` 必须无错。
- 项目 `newArchEnabled: true`，不得关闭。

## 文件结构

| 文件 | 职责 |
|---|---|
| `mobile/constants/ASR.ts` | 新建。ASR 采样率与帧长常量，与后端对齐的唯一来源 |
| `mobile/audio/pcm.ts` | 新建。纯函数：Float32→Int16 转换、RMS 计算 |
| `mobile/audio/bargeInDetector.ts` | 新建。打断判定状态机，纯逻辑、无音频依赖，可单测 |
| `mobile/hooks/useASR.ts` | 改造。音频采集后端换为 `AudioRecorder`；删除平台拦截；新增权限与会话生命周期 |
| `mobile/hooks/useTTS.ts` | 改造。`AudioContext` 换 import 来源；新增会话生命周期 |
| `mobile/app.json` | 增加 `react-native-audio-api` Expo plugin 配置 |

**关键决策：先抽取、后替换。** Task 2、3 在 **web 仍然可用的状态下**把打断检测逻辑抽成纯函数并加测试，验证行为未变；Task 4 才替换音频后端。这样若 Task 4 之后打断行为异常，可以确定问题出在音频后端而非判定逻辑。

---

### Task 1: 安装库与 Expo plugin 配置

**Files:**
- Modify: `mobile/package.json`
- Modify: `mobile/app.json`

**Interfaces:**
- Consumes: 无
- Produces: `react-native-audio-api` 可 import；Android 构建产物含 `RECORD_AUDIO` 权限

- [ ] **Step 1: 安装依赖**

```bash
cd mobile
npx expo install react-native-audio-api
```

用 `npx expo install` 而非 `npm install`：前者会挑选与 Expo SDK 54 兼容的版本。

- [ ] **Step 2: 配置 Expo plugin**

编辑 `mobile/app.json`，把 `plugins` 数组改成下面这样（保留已有的 `expo-router` 与 `expo-build-properties`，新增第三项）：

```json
    "plugins": [
      "expo-router",
      [
        "expo-build-properties",
        {
          "android": {
            "usesCleartextTraffic": true
          }
        }
      ],
      [
        "react-native-audio-api",
        {
          "androidPermissions": [
            "android.permission.RECORD_AUDIO"
          ]
        }
      ]
    ],
```

不加 `androidForegroundService`：本应用只在前台使用，老人看着屏幕说话，不需要后台录音，加了反而会多申请一组权限。

- [ ] **Step 3: 重新生成原生工程**

```bash
cd mobile
npx expo prebuild -p android --clean
```

`--clean` 会删掉旧的 `android/` 重新生成，确保新 plugin 的 manifest 改动生效。

⚠️ 这会**覆盖** `android/gradle.properties`。若之前为解决 `Unsupported class file major version 69` 在该文件里加过 `org.gradle.java.home`，需重新加回；更稳妥的做法是把它写在全局 `~/.gradle/gradle.properties` 里（该文件不会被 prebuild 覆盖）。

- [ ] **Step 4: 验证权限已写入 manifest**

```bash
cd mobile
grep RECORD_AUDIO android/app/src/main/AndroidManifest.xml
```

Expected: 输出含 `<uses-permission android:name="android.permission.RECORD_AUDIO"/>`

若无输出，说明 plugin 未生效，检查 Step 2 的 JSON 是否有语法错误（`npx expo config --type prebuild` 可打印解析后的配置）。

- [ ] **Step 5: 验证类型可解析**

```bash
cd mobile
npx tsc --noEmit
```

Expected: 无输出（无错误）

- [ ] **Step 6: 提交**

```bash
git add mobile/package.json mobile/package-lock.json mobile/app.json
git commit -m "chore(mobile): 引入 react-native-audio-api 与 Android 录音权限配置"
```

`android/` 目录是 prebuild 产物，若 `.gitignore` 已忽略则不提交；若未忽略，本步骤不要提交它，留待 Task 6 统一处理。

---

### Task 2: 抽取 PCM 纯函数

**Files:**
- Create: `mobile/constants/ASR.ts`
- Create: `mobile/audio/pcm.ts`
- Create: `mobile/audio/__tests__/pcm-test.ts`
- Modify: `mobile/hooks/useASR.ts`

**Interfaces:**
- Consumes: 无
- Produces:
  - `ASR_SAMPLE_RATE: number`（值 16000）、`ASR_FRAME_SAMPLES: number`（值 2048），来自 `@/constants/ASR`
  - `floatToInt16(samples: Float32Array): Int16Array`
  - `computeRms(samples: Float32Array): number`
  两个函数均来自 `@/audio/pcm`

- [ ] **Step 1: 写失败的测试**

创建 `mobile/audio/__tests__/pcm-test.ts`：

```ts
import { computeRms, floatToInt16 } from '@/audio/pcm';

describe('computeRms', () => {
  it('全零信号的 RMS 为 0', () => {
    expect(computeRms(new Float32Array([0, 0, 0, 0]))).toBe(0);
  });

  it('恒定幅值信号的 RMS 等于该幅值', () => {
    expect(computeRms(new Float32Array([0.5, -0.5, 0.5, -0.5]))).toBeCloseTo(0.5, 6);
  });

  it('RMS 与符号无关', () => {
    const positive = computeRms(new Float32Array([0.3, 0.3]));
    const mixed = computeRms(new Float32Array([0.3, -0.3]));
    expect(positive).toBeCloseTo(mixed, 6);
  });
});

describe('floatToInt16', () => {
  it('输出长度与输入一致', () => {
    expect(floatToInt16(new Float32Array(2048)).length).toBe(2048);
  });

  it('0 映射到 0', () => {
    expect(floatToInt16(new Float32Array([0]))[0]).toBe(0);
  });

  it('按 32768 缩放', () => {
    expect(floatToInt16(new Float32Array([0.5]))[0]).toBe(16384);
  });

  it('正向溢出被截断在 32767', () => {
    // 1.0 * 32768 = 32768，超出 Int16 上限，必须截到 32767，
    // 否则会回绕成 -32768（一声爆音）
    expect(floatToInt16(new Float32Array([1.0]))[0]).toBe(32767);
    expect(floatToInt16(new Float32Array([2.5]))[0]).toBe(32767);
  });

  it('负向溢出被截断在 -32768', () => {
    expect(floatToInt16(new Float32Array([-2.5]))[0]).toBe(-32768);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd mobile
npx jest audio/__tests__/pcm-test.ts
```

Expected: FAIL，报 `Cannot find module '@/audio/pcm'`

- [ ] **Step 3: 写常量文件**

创建 `mobile/constants/ASR.ts`：

```ts
/**
 * ASR 上行音频参数。
 *
 * ⚠️ 必须与后端 `backend/config.py` 的 ASR_SAMPLE_RATE / ASR_FRAME_SAMPLES
 * 严格一致，后端按这个约定切帧。
 *
 * 另外，`constants/BargeIn.ts` 里 SUSTAINED_FRAMES、PREBUFFER_FRAMES 的取值
 * 都是按「每帧约 128ms」推算的（2048 / 16000 ≈ 0.128s）。改这里的值会让那些
 * 注释里的毫秒推算全部失真，必须一并复核。
 */
export const ASR_SAMPLE_RATE = 16000;
export const ASR_FRAME_SAMPLES = 2048;
```

- [ ] **Step 4: 写实现**

创建 `mobile/audio/pcm.ts`：

```ts
/**
 * PCM 采样的纯函数工具。
 *
 * 从 useASR 的音频回调里抽出来，好处有二：一是这部分逻辑可以脱离音频硬件
 * 单测，二是替换音频后端时能确定它没被改动。
 */

/** 帧能量（RMS）。与后端 ASRService.compute_rms 同一算法。 */
export const computeRms = (samples: Float32Array): number => {
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
};

/**
 * Float32（-1.0~1.0）转 Int16，后端要的是 16 位小端 PCM。
 *
 * 上下界必须截断：1.0 * 32768 = 32768 已超出 Int16 上限，直接写进
 * Int16Array 会回绕成 -32768，听感上是一声爆音。
 */
export const floatToInt16 = (samples: Float32Array): Int16Array => {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    out[i] = Math.max(-32768, Math.min(32767, samples[i] * 32768));
  }
  return out;
};
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd mobile
npx jest audio/__tests__/pcm-test.ts
```

Expected: PASS，11 个断言全过

- [ ] **Step 6: 让 useASR 改用抽出来的函数**

编辑 `mobile/hooks/useASR.ts`：

1. 删除文件里原有的 `computeRms` 局部定义（在 `interface UseASROptions` 之后、`export const useASR` 之前，约 15-21 行）。

2. 在文件顶部 import 区加入：

```ts
import { computeRms, floatToInt16 } from '../audio/pcm';
import { ASR_FRAME_SAMPLES, ASR_SAMPLE_RATE } from '../constants/ASR';
```

3. 在 `processor.onaudioprocess` 回调里，把这段：

```ts
        const inputData = e.inputBuffer.getChannelData(0);
        // Convert Float32 to Int16
        const pcmData = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          pcmData[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32768));
        }
```

替换为：

```ts
        const inputData = e.inputBuffer.getChannelData(0);
        const pcmData = floatToInt16(inputData);
```

4. 把 `new AudioContext({ sampleRate: 16000 })` 改为 `new AudioContext({ sampleRate: ASR_SAMPLE_RATE })`。

5. 把 `audioContext.createScriptProcessor(2048, 1, 1)` 改为 `audioContext.createScriptProcessor(ASR_FRAME_SAMPLES, 1, 1)`。

6. 把 `getUserMedia` 里的 `sampleRate: 16000` 改为 `sampleRate: ASR_SAMPLE_RATE`。

- [ ] **Step 7: 验证类型与全量测试**

```bash
cd mobile
npx tsc --noEmit && npm test
```

Expected: tsc 无输出；jest 全部通过（含既有的 MemoryGame、useMemoryGame、smoke 三组）

- [ ] **Step 8: 提交**

```bash
git add mobile/constants/ASR.ts mobile/audio/pcm.ts mobile/audio/__tests__/pcm-test.ts mobile/hooks/useASR.ts
git commit -m "refactor(mobile): 抽出 PCM 纯函数并补测试，ASR 帧参数收进常量"
```

---

### Task 3: 抽取打断判定状态机

打断检测目前整个埋在 `processor.onaudioprocess` 的闭包里，跟音频硬件绑死，无法测试。
本任务把它抽成一个纯状态机：**输入是 RMS 与时间戳，输出是「这一帧是否判定为打断」**，
不碰 ArrayBuffer、不碰 WebSocket。预缓冲（`preBufferRef`）留在 hook 里不动——它处理的是
待发送的字节，属于传输关注点，不属于判定逻辑。

**Files:**
- Create: `mobile/audio/bargeInDetector.ts`
- Create: `mobile/audio/__tests__/bargeInDetector-test.ts`
- Modify: `mobile/hooks/useASR.ts`

**Interfaces:**
- Consumes: `BARGE_IN` 来自 `@/constants/BargeIn`
- Produces:
  - `interface BargeInConfig { ENABLED: boolean; GRACE_MS: number; BASELINE_MS: number; THRESHOLD_RATIO: number; MIN_THRESHOLD_RMS: number; SUSTAINED_FRAMES: number; }`
  - `class BargeInDetector`，构造签名 `constructor(config?: BargeInConfig)`（缺省用 `BARGE_IN`）
  - 方法 `reset(nowMs: number): void`
  - 方法 `process(rms: number, nowMs: number): boolean`（返回 true 表示本帧判定为打断）
  - 只读属性 `threshold: number`（供日志打印，测试也用它断言阈值计算）

- [ ] **Step 1: 写失败的测试**

创建 `mobile/audio/__tests__/bargeInDetector-test.ts`：

```ts
import { BargeInDetector, BargeInConfig } from '@/audio/bargeInDetector';

// 测试用配置。刻意不复用 constants/BargeIn.ts 的真实数值——那些值会随实地调参
// 变动，测试不该跟着一起坏。这里用好算的整数。
const CONFIG: BargeInConfig = {
  ENABLED: true,
  BASELINE_MS: 300,
  GRACE_MS: 500,
  THRESHOLD_RATIO: 3,
  MIN_THRESHOLD_RMS: 0.02,
  SUSTAINED_FRAMES: 3,
};

const T0 = 1_000_000;

/** 喂 n 帧同样的 rms，返回是否在其中某一帧判定为打断。 */
const feed = (d: BargeInDetector, rms: number, times: number[]): boolean =>
  times.reduce((hit, t) => d.process(rms, t) || hit, false);

describe('BargeInDetector', () => {
  it('底噪采样期内不判打断，无论多响', () => {
    const d = new BargeInDetector(CONFIG);
    d.reset(T0);
    // BASELINE_MS = 300，这三帧都在采样期内
    expect(feed(d, 0.9, [T0 + 0, T0 + 100, T0 + 200])).toBe(false);
  });

  it('阈值 = 底噪均值 × THRESHOLD_RATIO', () => {
    const d = new BargeInDetector(CONFIG);
    d.reset(T0);
    // 采样期喂恒定 0.1 的底噪
    d.process(0.1, T0 + 0);
    d.process(0.1, T0 + 100);
    d.process(0.1, T0 + 200);
    // 跨过 BASELINE_MS，此帧触发阈值计算
    d.process(0.1, T0 + 350);
    expect(d.threshold).toBeCloseTo(0.3, 6); // 0.1 * 3
  });

  it('底噪极低时阈值被 MIN_THRESHOLD_RMS 兜住', () => {
    const d = new BargeInDetector(CONFIG);
    d.reset(T0);
    // 极安静的房间：0.001 * 3 = 0.003，远低于下限 0.02
    d.process(0.001, T0 + 0);
    d.process(0.001, T0 + 200);
    d.process(0.001, T0 + 350);
    expect(d.threshold).toBeCloseTo(0.02, 6);
  });

  it('保护期内不判打断，即使已超阈值', () => {
    const d = new BargeInDetector(CONFIG);
    d.reset(T0);
    d.process(0.1, T0 + 100); // 底噪
    d.process(0.1, T0 + 200);
    // GRACE_MS = 500。下面三帧都超阈值(0.3)但仍在保护期内
    expect(feed(d, 0.9, [T0 + 350, T0 + 400, T0 + 450])).toBe(false);
  });

  it('保护期后连续 SUSTAINED_FRAMES 帧超阈值才判打断', () => {
    const d = new BargeInDetector(CONFIG);
    d.reset(T0);
    d.process(0.1, T0 + 100);
    d.process(0.1, T0 + 200);
    d.process(0.1, T0 + 350); // 算出阈值 0.3
    // 保护期后，前两帧不够
    expect(d.process(0.9, T0 + 600)).toBe(false);
    expect(d.process(0.9, T0 + 728)).toBe(false);
    // 第三帧凑满
    expect(d.process(0.9, T0 + 856)).toBe(true);
  });

  it('中间掉回阈值以下会清零计数，需重新连续累积', () => {
    const d = new BargeInDetector(CONFIG);
    d.reset(T0);
    d.process(0.1, T0 + 100);
    d.process(0.1, T0 + 200);
    d.process(0.1, T0 + 350);
    d.process(0.9, T0 + 600); // 1
    d.process(0.9, T0 + 728); // 2
    d.process(0.05, T0 + 856); // 掉下去，清零
    // 又攒两帧还不够
    expect(d.process(0.9, T0 + 984)).toBe(false);
    expect(d.process(0.9, T0 + 1112)).toBe(false);
    expect(d.process(0.9, T0 + 1240)).toBe(true);
  });

  it('ENABLED 为 false 时永不判打断', () => {
    const d = new BargeInDetector({ ...CONFIG, ENABLED: false });
    d.reset(T0);
    expect(feed(d, 0.9, [T0 + 600, T0 + 728, T0 + 856, T0 + 984])).toBe(false);
  });

  it('reset 清空上一轮状态，新一轮重新测底噪', () => {
    const d = new BargeInDetector(CONFIG);
    d.reset(T0);
    d.process(0.1, T0 + 100);
    d.process(0.1, T0 + 350);
    expect(d.threshold).toBeCloseTo(0.3, 6);

    // 新一轮：房间变吵了，底噪 0.2
    const T1 = T0 + 100_000;
    d.reset(T1);
    expect(d.threshold).toBe(0);   // 已清零
    d.process(0.2, T1 + 100);
    d.process(0.2, T1 + 350);
    expect(d.threshold).toBeCloseTo(0.6, 6); // 按新底噪重算
  });

  it('判定打断后计数清零，不会连续重复触发', () => {
    const d = new BargeInDetector(CONFIG);
    d.reset(T0);
    d.process(0.1, T0 + 100);
    d.process(0.1, T0 + 350);
    d.process(0.9, T0 + 600);
    d.process(0.9, T0 + 728);
    expect(d.process(0.9, T0 + 856)).toBe(true);
    // 紧接着的下一帧仍然很响，但计数已清零，不该再报
    expect(d.process(0.9, T0 + 984)).toBe(false);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd mobile
npx jest audio/__tests__/bargeInDetector-test.ts
```

Expected: FAIL，报 `Cannot find module '@/audio/bargeInDetector'`

- [ ] **Step 3: 写实现**

创建 `mobile/audio/bargeInDetector.ts`：

```ts
import { BARGE_IN } from '../constants/BargeIn';

export interface BargeInConfig {
  ENABLED: boolean;
  BASELINE_MS: number;
  GRACE_MS: number;
  THRESHOLD_RATIO: number;
  MIN_THRESHOLD_RMS: number;
  SUSTAINED_FRAMES: number;
}

/**
 * 打断判定状态机。
 *
 * 每轮 TTS 播放开始时 reset()，之后每来一帧麦克风数据调一次 process()。
 * 判定分三阶段：先用开头一小段测房间底噪，据此算出阈值（而非写死绝对值——
 * 不同房间、不同音量差别很大），随后要连续若干帧超阈值才认定是真的有人在说话，
 * 以此滤掉咳嗽、关门、电视里的单个爆音。
 *
 * 刻意只处理数值：输入 RMS 与时间戳，输出布尔。预缓冲的字节、WebSocket 发送都在
 * 调用方，这样这套判定逻辑可以脱离音频硬件单测。
 */
export class BargeInDetector {
  private config: BargeInConfig;
  private startedAt = 0;
  private baseline: number[] = [];
  private sustained = 0;
  private _threshold = 0;

  constructor(config: BargeInConfig = BARGE_IN) {
    this.config = config;
  }

  /** 当前判定阈值。0 表示还没算出来（底噪采样未完成）。 */
  get threshold(): number {
    return this._threshold;
  }

  /** 新一轮 TTS 开始，清空上一轮状态。 */
  reset(nowMs: number): void {
    this.startedAt = nowMs;
    this.baseline = [];
    this.sustained = 0;
    this._threshold = 0;
  }

  /** 喂一帧。返回 true 表示本帧判定为老人插话。 */
  process(rms: number, nowMs: number): boolean {
    if (!this.config.ENABLED) return false;

    const elapsed = nowMs - this.startedAt;

    // 阶段一：测环境底噪。这段时间喇叭在响，但 AEC 已经把它消掉大半，
    // 读数基本是房间本底。
    if (elapsed < this.config.BASELINE_MS) {
      this.baseline.push(rms);
      return false;
    }

    // 阶段二：底噪采完，算一次阈值
    if (this._threshold === 0) {
      const mean = this.baseline.length
        ? this.baseline.reduce((a, b) => a + b, 0) / this.baseline.length
        : 0;
      this._threshold = Math.max(
        mean * this.config.THRESHOLD_RATIO,
        this.config.MIN_THRESHOLD_RMS,
      );
    }

    // 保护期内不判打断，避免老人自己上一句的尾音把回复刚开头就掐掉
    if (elapsed < this.config.GRACE_MS) return false;

    // 阶段三：连续超阈值才算
    if (rms > this._threshold) {
      this.sustained += 1;
    } else {
      this.sustained = 0;
      return false;
    }
    if (this.sustained < this.config.SUSTAINED_FRAMES) return false;

    // 判定成立。计数清零，避免后续每一帧都重复上报。
    this.sustained = 0;
    return true;
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd mobile
npx jest audio/__tests__/bargeInDetector-test.ts
```

Expected: PASS，9 个用例全过

- [ ] **Step 5: 让 useASR 改用状态机**

编辑 `mobile/hooks/useASR.ts`：

1. 顶部 import 加入：

```ts
import { BargeInDetector } from '../audio/bargeInDetector';
```

2. 删除这四个 ref 声明（打断判定状态已搬进状态机，预缓冲保留）：

```ts
  const ttsStartedAtRef = useRef(0);
  const baselineRmsRef = useRef<number[]>([]);
  const thresholdRef = useRef(0);
  const sustainedRef = useRef(0);
```

改为一个：

```ts
  const detectorRef = useRef<BargeInDetector>(new BargeInDetector());
```

3. `resetBargeInState` 改为：

```ts
  /** 重置一轮 TTS 的打断检测状态。 */
  const resetBargeInState = useCallback(() => {
    detectorRef.current.reset(Date.now());
    preBufferRef.current = [];
  }, []);
```

4. 在 `processor.onaudioprocess` 里，把从 `if (!BARGE_IN.ENABLED) return;` 起、到 `onBargeInRef.current?.();` 为止的整段判定逻辑（原约 205-256 行），替换为：

```ts
        if (!detectorRef.current.process(computeRms(inputData), Date.now())) return;

        // ── 判定为插话 ──
        console.log('[BargeIn] 检测到插话');
        isTTSMutedRef.current = false;      // 立刻恢复收音，不等 tts-end 的 200ms 去抖
        if (unmuteTimeoutRef.current) {
          clearTimeout(unmuteTimeoutRef.current);
          unmuteTimeoutRef.current = null;
        }
        // 先补发预缓冲，老人开口的头几个字才不会丢
        preBufferRef.current.forEach(sendFrame);
        preBufferRef.current = [];

        onBargeInRef.current?.();
```

注意保留上方「存预缓冲」那几行不动：

```ts
        const pre = preBufferRef.current;
        pre.push(pcmData.buffer);
        if (pre.length > BARGE_IN.PREBUFFER_FRAMES) pre.shift();
```

5. 若 `BARGE_IN` 在文件里已无其他引用（除 `PREBUFFER_FRAMES` 外），保留该 import 即可，不要删。

- [ ] **Step 6: 验证类型与全量测试**

```bash
cd mobile
npx tsc --noEmit && npm test
```

Expected: tsc 无输出；jest 全部通过

- [ ] **Step 7: web 端行为确认（抽取未改变行为）**

```bash
cd mobile
npx expo start --web
```

浏览器打开后按「我想和你聊聊」，说一句话，等 AI 回复时打断它。确认：
- 控制台出现 `[BargeIn] 检测到插话`
- AI 立即停声
- 屏幕上那条回复被截断在实际听到的位置

**这一步是本任务的关键验证**：音频后端还没换，若此时打断行为与改造前一致，
即可确定抽取是行为保持的；Task 4 之后若打断异常，问题必定在音频后端。

- [ ] **Step 8: 提交**

```bash
git add mobile/audio/bargeInDetector.ts mobile/audio/__tests__/bargeInDetector-test.ts mobile/hooks/useASR.ts
git commit -m "refactor(mobile): 打断判定抽成可单测的状态机"
```

---

### Task 4: useASR 换用 AudioRecorder

本任务替换录音后端并删除平台拦截。**这是整个计划里唯一可能触发 spec §8.1
（Android AEC）风险的任务**，若真机上出现「AI 刚开口就自己掐断自己、反复循环」，
即为该风险兑现，停下来按 spec §8.1 列出的补偿路径重新讨论，不要试图靠调参硬扛。

**Files:**
- Modify: `mobile/hooks/useASR.ts`

**Interfaces:**
- Consumes: `floatToInt16` / `computeRms`（Task 2）、`BargeInDetector`（Task 3）、`ASR_SAMPLE_RATE` / `ASR_FRAME_SAMPLES`（Task 2）
- Produces: `useASR` 返回值不变 —— `{ start, stop, status, isRecording, analyser }`

- [ ] **Step 1: 换 import**

编辑 `mobile/hooks/useASR.ts` 顶部：

删除 `Platform` 的引用（下一步会删掉唯一用到它的地方）：

```ts
import { DeviceEventEmitter } from 'react-native';
```

新增：

```ts
import { AudioContext, AudioManager, AudioRecorder } from 'react-native-audio-api';
```

- [ ] **Step 2: 换 ref 类型**

把这两行：

```ts
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
```

替换为：

```ts
  const recorderRef = useRef<AudioRecorder | null>(null);
```

`audioContextRef` 与 `analyserRef` 保留，但类型改用库里的：

```ts
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
```

`AnalyserNode` 需从 `react-native-audio-api` 一并 import。

- [ ] **Step 3: 改写 stop()**

把 `stop` 里处理 processor / stream 的两段：

```ts
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
```
和
```ts
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
```

替换为（放在 analyser 处理之前）：

```ts
    if (recorderRef.current) {
      recorderRef.current.clearOnAudioReady();
      recorderRef.current.stop();
      recorderRef.current = null;
    }
```

并在 `audioContextRef.current.close()` 之后追加一行释放音频会话：

```ts
    AudioManager.setAudioSessionActivity(false).catch(() => {
      // 释放失败不影响用户，下次 start 会重新激活
    });
```

`stop` 保持同步函数（`useEffect` 的 cleanup 依赖它），所以这里用 `.catch()` 而非 `await`。

- [ ] **Step 4: 改写 start() 的开头——权限与会话**

把这段平台拦截：

```ts
    if (Platform.OS !== 'web') {
      console.warn('Real-time audio capture is currently optimized for Web/Laptop testing.');
      return;
    }
```

替换为：

```ts
    // 麦克风权限。web 端浏览器会自己弹窗，原生端必须显式申请。
    const permission = await AudioManager.requestRecordingPermissions();
    if (permission !== 'Granted') {
      onError?.('我听不见您说话，请在手机设置里允许使用麦克风。');
      return;
    }

    try {
      await AudioManager.setAudioSessionActivity(true);
    } catch {
      onError?.('麦克风打不开，请再试一次。');
      return;
    }
```

- [ ] **Step 5: 改写 start() 的音频图搭建**

把「2. Setup Audio Capture (Web)」整段（从 `const stream = await navigator.mediaDevices.getUserMedia({` 起，到 `processor.connect(audioContext.destination);` 止）替换为：

```ts
      // 2. 音频采集
      const audioContext = new AudioContext({ sampleRate: ASR_SAMPLE_RATE });
      audioContextRef.current = audioContext;

      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.8;
      analyserRef.current = analyser;

      const recorder = new AudioRecorder();
      recorderRef.current = recorder;
      // 接进音频图，Waveform / Orb 靠 analyser 取数据画图
      recorder.connect(audioContext, analyser);

      const sendFrame = (buf: ArrayBuffer) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(buf);
        }
      };

      recorder.onAudioReady(
        {
          sampleRate: ASR_SAMPLE_RATE,
          bufferLength: ASR_FRAME_SAMPLES,
          channelCount: 1,
        },
        ({ buffer }) => {
          const inputData = buffer.getChannelData(0);
          const pcmData = floatToInt16(inputData);

          // 正常收音
          if (!isTTSMutedRef.current) {
            sendFrame(pcmData.buffer);
            return;
          }

          // ── TTS 播放期间：不往云端发（防回声），但本地判断有没有人在插话 ──
          const pre = preBufferRef.current;
          pre.push(pcmData.buffer);
          if (pre.length > BARGE_IN.PREBUFFER_FRAMES) pre.shift();

          if (!detectorRef.current.process(computeRms(inputData), Date.now())) return;

          // ── 判定为插话 ──
          console.log('[BargeIn] 检测到插话');
          isTTSMutedRef.current = false;      // 立刻恢复收音，不等 tts-end 的 200ms 去抖
          if (unmuteTimeoutRef.current) {
            clearTimeout(unmuteTimeoutRef.current);
            unmuteTimeoutRef.current = null;
          }
          // 先补发预缓冲，老人开口的头几个字才不会丢
          preBufferRef.current.forEach(sendFrame);
          preBufferRef.current = [];

          onBargeInRef.current?.();
        },
      );

      const result = await recorder.start();
      if (result.status === 'error') {
        console.error('[useASR] 录音启动失败:', result.message);
        onError?.('麦克风打不开，请再试一次。');
        stop();
        return;
      }
```

⚠️ **实现时需确认 `onAudioReady` 回调参数的确切形状**。文档给出的是
`({ buffer, numFrames, when }) => {}`，本计划按 `buffer.getChannelData(0)` 取样本。
若实际给的是裸 `Float32Array`，则改为直接使用 `buffer`。写完先跑 Step 7 的 web 验证，
控制台打一行 `console.log(typeof buffer, buffer)` 即可确认，确认后删掉该调试行。

- [ ] **Step 6: 验证类型与全量测试**

```bash
cd mobile
npx tsc --noEmit && npm test
```

Expected: tsc 无输出；jest 全部通过

若 tsc 报 `Platform` 已声明但未使用，删掉该 import。

- [ ] **Step 6a（本步在实现期间新增，见 spec §4.1a 修订）：装 react-native-gesture-handler**

`react-native-audio-api` 的 web 入口无条件引入自带的音频控件组件，依赖
`react-native-gesture-handler`。不装的话 `useASR.ts` 一 import 这个库，
web 端 bundle 直接编译失败——**不只是录音功能受影响，聊聊天/练练脑/我自己三个
tab 的 web 版全部起不来**。

```bash
cd mobile
npx expo install react-native-gesture-handler
```

- [ ] **Step 7: web 端回归验证（范围已按 spec §4.1a 修订）**

```bash
cd mobile
npx expo start --web
```

逐项确认：
- [ ] 三个 tab 都能正常打开，bundle 编译无报错（验证 Step 6a 的补装解决了编译失败）
- ~~按「我想和你聊聊」能开始录音~~ **不适用**：`AudioRecorder` 在 web 构建里不存在
  （spec §4.1a），点击后台无反应是预期行为，不是缺陷，不用管
- [ ] AI 回复能出声（放音不受影响，仍需验证）
- ~~AI 说话时插话能打断~~ **不适用**：依赖录音侧检测，移至 Task 6 的 Android 验证
- [ ] Waveform（切到「看文字」模式）在 TTS 播放时随声音起伏

任何一项标了「仍需验证」的不过，先修好再进 Step 8——不要带着回归上真机。

- [ ] **Step 8: 提交**

```bash
git add mobile/hooks/useASR.ts mobile/package.json mobile/package-lock.json
git commit -m "feat(mobile): ASR 录音改用 react-native-audio-api，去掉平台拦截

react-native-audio-api 的 web 构建没有 AudioRecorder（见 spec §4.1a），
接受 web 端录音不可用，不再维护该路径；补装 react-native-gesture-handler
解决因此产生的 web 编译失败。"
```

---

### Task 5: useTTS 换用库的 AudioContext

`useTTS.ts` 的播放调度逻辑（`fetchAndSchedule` / `scheduleRef` / `getSpokenText` /
`haltAudio`）**一行都不改**——它依赖的 `createBuffer` / `createBufferSource` /
`start(when)` / `currentTime` 在 `react-native-audio-api` 里签名语义完全一致。
本任务只换 `AudioContext` 的来源。

**Files:**
- Modify: `mobile/hooks/useTTS.ts`

**Interfaces:**
- Consumes: 无（Task 1 装好的库）
- Produces: `useTTS` 返回值不变 —— `{ speak, stop, stopForBargeIn, getSpokenText, resetSpokenText, isPlaying, isPlayingRef }`

- [ ] **Step 1: 换 import**

编辑 `mobile/hooks/useTTS.ts` 顶部，在已有的 `DeviceEventEmitter` 那行之后加：

```ts
import { AudioBufferSourceNode, AudioContext } from 'react-native-audio-api';
```

- [ ] **Step 2: 换 ref 类型**

把：

```ts
  const audioCtxRef = useRef<AudioContext | null>(null);
```

保持不变（现在指向库的类型了）。把：

```ts
  const scheduledSourcesRef = useRef<AudioBufferSourceNode[]>([]);
```

也保持不变（同理）。这两行文本不用动，只是它们引用的类型来源变了。

- [ ] **Step 3: 改写 initAudio()**

把：

```ts
      audioCtxRef.current = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: TTS_CONFIG.SAMPLE_RATE,
      });
```

替换为：

```ts
      audioCtxRef.current = new AudioContext({
        sampleRate: TTS_CONFIG.SAMPLE_RATE,
      });
```

`window.AudioContext || window.webkitAudioContext` 这个兼容写法是给老浏览器的，
库已经处理了平台差异，不需要了。

- [ ] **Step 4: 验证类型与全量测试**

```bash
cd mobile
npx tsc --noEmit && npm test
```

Expected: tsc 无输出；jest 全部通过

若 tsc 在 `source.onended = () => {...}` 或 `audioCtxRef.current.suspend()` 处报类型不符，
说明库的类型定义与浏览器 DOM 类型有出入，按库的类型签名调整，**不要用 `as any` 绕过**——
那会把真正的 API 差异藏到运行时。

- [ ] **Step 5: web 端回归验证**

```bash
cd mobile
npx expo start --web
```

逐项确认：
- [ ] AI 回复能出声
- [ ] 多句回复之间**没有卡顿**（验证 `nextStartTimeRef` 的无缝排期仍然生效）
- [ ] 打断后立即停声（验证 `haltAudio` 的 `source.stop()` 仍然生效）
- [ ] 打断后屏幕文字截断位置与实际听到的一致（验证 `currentTime` 语义一致）
- [ ] 「结束对话」能把告别播完再清屏（验证 `onPlaybackDone` 链路）

第 4 项最关键：它验证的是 `getSpokenText()` 依赖的 `ctx.currentTime` 在新库里
含义没变。若截断位置明显偏前或偏后，说明 `currentTime` 的时间基准不同，需要
在 `fetchAndSchedule` 里改用同一基准记录 `scheduleRef`。

- [ ] **Step 6: 提交**

```bash
git add mobile/hooks/useTTS.ts
git commit -m "feat(mobile): TTS 播放改用 react-native-audio-api 的 AudioContext"
```

---

### Task 6: Android 端验证与收尾

前五个任务都在 web 上验证。本任务第一次在 Android 上真正跑起来，并把验证结果与
遗留问题记进备忘录。

**Files:**
- Modify: `implementation-notes.html`
- Modify: `.gitignore`（若 `android/` 尚未忽略）

**Interfaces:**
- Consumes: Task 1-5 的全部产出
- Produces: 无代码产出，产出是验证结论

- [ ] **Step 1: 构建并安装到设备**

真机优先（模拟器的麦克风行为不可靠，尤其 AEC 相关）。手机开 USB 调试后：

```bash
cd mobile/android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Windows 上 `./gradlew` 不认时用 `gradlew.bat assembleDebug`。

- [ ] **Step 2: 开日志窗口**

另开一个终端，只看本应用的日志：

```bash
adb logcat -c && adb logcat ReactNativeJS:V AndroidRuntime:E *:S
```

`adb logcat -c` 先清掉旧日志。`ReactNativeJS` 是 JS 侧 `console.*` 的输出通道，
`[BargeIn]`、`[useASR]` 这些日志会出现在这里。

- [ ] **Step 3: 逐项手测**

按顺序做，每项记下结果：

- [ ] 首次进入按「我想和你聊聊」，**弹出麦克风权限申请**
- [ ] 点「拒绝」，屏幕出现「我听不见您说话，请在手机设置里允许使用麦克风。」，**应用不崩**
- [ ] 到设置里授予权限后重进，能开始录音
- [ ] 说一句话，**屏幕出字**（打通了：录音 → 16kHz/2048 帧 → WebSocket → 后端 ASR）
- [ ] AI **能出声**（打通了：SSE → TTS 流 → 原生播放）
- [ ] 多句回复之间无明显卡顿
- [ ] AI 说话时插话，**能打断**，且屏幕文字截断在实际听到的位置
- [ ] 「结束对话」能播完告别再清屏
- [ ] 切到「练练脑」再切回来，重新开始对话仍正常（验证 stop/start 的资源释放）

上面第 4、5 项**必须一次会话内连着做**（说完话紧接着听 AI 回复），因为这是唯一能
暴露 spec §8.2 的场景 —— 见下一步。

- [ ] **Step 4: 判定「双 AudioContext 采样率」风险（spec §8.2）**

ASR 侧开的是 16kHz 的 `AudioContext`，TTS 侧开的是 24kHz 的，**两者在一次对话里同时
存在**。原生端能否并存两个不同采样率的 context，库文档未说明；浏览器允许，所以
前面的 web 回归测不出这个问题。

盯住这三种现象（任一出现即为风险兑现）：

- 开始录音后 AI 的声音**变调**（听起来偏尖或偏闷）或**语速不对**
  —— 说明第二个 context 被强制对齐到第一个的采样率，24kHz 数据按 16kHz 播了
- 创建第二个 context 时**抛异常**，logcat 里出现 sample rate 相关报错
- 录音正常但 TTS 完全无声（或反之）

若出现 → 退路是**统一到单一采样率**：`useTTS` 复用 16kHz 的 context，在
`fetchAndSchedule` 里把后端来的 24kHz PCM 重采样到 16kHz 后再
`createBuffer`。这会改动 Task 5 明确声明「一行不改」的那段逻辑，属于设计变更，
**先停下来说明，不要直接改**。

隔离手段：单独只按「我想和你聊聊」但不说话（只有 ASR context），再单独触发一次
主动招呼（只有 TTS context），若各自都正常、合起来才出问题，即可确认是并存导致的。

- [ ] **Step 5: 判定 AEC 风险是否兑现（spec §8.1）**

盯住这个现象：**AI 一开口就被自己掐断，`[BargeIn] 检测到插话` 在没人说话时反复刷屏。**

若出现 → spec §8.1 的风险兑现，Android 没有可用 AEC。**停下来，不要调参硬扛**，
按 spec §8.1 的三条补偿路径重新讨论：

1. 自研简易回声抑制（拿已知的 TTS 输出做参考信号）
2. 混合判据：TTS 播放期间大幅提高阈值 + 依赖 ASR 返回文本二次确认
3. 降级：`constants/BargeIn.ts` 里 `ENABLED: false`，退回「不能打断」的老行为

临时确认手段：把 `constants/BargeIn.ts` 的 `ENABLED` 改成 `false` 重装，
若其余功能全部正常，即可确认问题隔离在打断检测这一块。

- [ ] **Step 6: 忽略 prebuild 产物**

```bash
cd D:/MyPrograms/zht/agetalker
grep -q "^mobile/android/" .gitignore || printf '\n# Expo prebuild 产物，由 app.json 生成，不入库\nmobile/android/\nmobile/ios/\n' >> .gitignore
```

`android/` 是 `expo prebuild` 的产物，改 `app.json` 重跑就会重新生成，不该入库
（它体积大、且每次 prebuild 都会产生大量无意义 diff）。

⚠️ 若团队里有人手工改过 `android/` 里的原生文件（例如为解决 JDK 版本问题加的
`org.gradle.java.home`），忽略之后这些改动会丢。这类配置应当放在
`~/.gradle/gradle.properties`（全局，不受 prebuild 影响）或写成 Expo config plugin。

- [ ] **Step 7: 记入实现备忘录**

编辑 `implementation-notes.html`，在 `</main>` 之前追加一节（沿用文件既有的
`<div class="card">` / `<div class="card warn">` 样式）：

```html
<h2>17. 原生端音频管线（2026-08-19）</h2>

<div class="card">
<h4>17.1 根因不是那个崩溃，是整条链路从没在原生端实现过</h4>
<p>APK 启动报 <code>window.addEventListener is not a function</code>，表面看是
事件监听写法的问题（已改用 RN 的 <code>DeviceEventEmitter</code>）。但真正的根因是
录音与放音<strong>整体建立在浏览器 Web Audio / WebRTC API 之上</strong>——
<code>getUserMedia</code>、<code>AudioContext</code>、<code>createScriptProcessor</code>
在原生运行时里都不存在。<code>useASR.ts</code> 里甚至有一道显式拦截
<code>if (Platform.OS !== 'web') return;</code>，即原生端按下按钮只是静默返回。
这是一直待办的工作，不是回归。</p>
</div>

<div class="card">
<h4>17.2 两端统一，而非给原生加一条分支</h4>
<p>选用 <code>react-native-audio-api</code>（Web Audio API 规范的 RN 实现）的决定性
理由是<strong>它在 web 上也能跑</strong>（转调浏览器原生实现），因此可以删掉
<code>Platform.OS</code> 拦截，两端走同一套 API。</p>
<p>代价是 web 端也跟着换了音频后端，必须完整重测；收益是长期只维护一套逻辑。
若走「加原生分支」，两条路径会各自演化，web 上调好的打断参数在原生上对不上，
最终要调两遍且永远无法确认两边一致。</p>
</div>

<div class="card">
<h4>17.3 先抽取、后替换</h4>
<p>打断判定原本整个埋在 <code>onaudioprocess</code> 闭包里，跟音频硬件绑死无法测试。
改造分两步：先在 <strong>web 仍可用的状态下</strong>把它抽成纯状态机
（<code>audio/bargeInDetector.ts</code>，9 个单测覆盖底噪采样、阈值计算、
保护期、连续帧判定、reset 语义），确认行为未变；之后才替换音频后端。</p>
<p>这样若替换后打断异常，可以确定问题在音频后端而非判定逻辑——两个变量分开验证。</p>
</div>

<div class="card warn">
<h4>17.4 最大的未知：Android 回声消除</h4>
<p>打断检测的阈值模型建立在「AEC 已消掉喇叭声，麦克风收到的基本是房间本底」
这一前提上（见 <code>constants/BargeIn.ts</code> 顶部注释）。web 端靠的是
<code>getUserMedia({echoCancellation: true})</code>。</p>
<p>而 <code>react-native-audio-api</code> 的 README roadmap 里，回声消除仍列为
<strong>Planned</strong>；<code>SessionOptions</code> 中 AEC 相关配置<strong>只有 iOS 项</strong>；
<code>AudioRecorder</code> 也没有 <code>echoCancellation</code> 参数。Android 底层若内部
用的是 <code>VOICE_COMMUNICATION</code> 采集源则会自动挂硬件 AEC，用 <code>MIC</code>
则没有——文档未说明。</p>
<p><strong>本次改造按「有 AEC」的乐观假设推进（已与需求方确认）。</strong>若无 AEC，
表现是「AI 刚开口就被自己掐断、反复循环」——不是精度问题，是功能不可用。
补偿路径见设计文档 §8.1。</p>
</div>
```

- [ ] **Step 8: 提交**

```bash
cd D:/MyPrograms/zht/agetalker
git add implementation-notes.html .gitignore
git commit -m "docs: 原生音频管线实现备忘录与 prebuild 产物忽略规则"
```

---

## 完成标准

全部任务做完后，下列条件同时成立才算完成：

1. `npx tsc --noEmit` 无错
2. `npm test` 全部通过（含新增的 pcm 11 个断言、bargeInDetector 9 个用例）
3. web 端 Task 4 Step 7 与 Task 5 Step 5 的检查项全部通过
4. Android 端 Task 6 Step 3 的九项手测全部通过
5. `mobile/app/(tabs)/index.tsx`、`components/Waveform.tsx`、`components/OrbVisualizer.tsx`
   三个文件的 diff 为空

若第 4 项因 AEC 风险无法全部通过，**不算失败**——按 Task 6 Step 4 停下来重新讨论，
并把实测结论补进设计文档 §8.1。
