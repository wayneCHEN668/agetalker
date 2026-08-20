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
