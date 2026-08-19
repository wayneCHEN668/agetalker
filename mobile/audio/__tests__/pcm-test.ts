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
