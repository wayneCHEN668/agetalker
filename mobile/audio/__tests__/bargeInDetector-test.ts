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
