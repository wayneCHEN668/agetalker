import { computeRms, createPcmStreamDecoder, floatToInt16 } from '@/audio/pcm';

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

describe('createPcmStreamDecoder', () => {
  /** 小端 16 位字节序列，便于构造测试输入 */
  const le = (...samples: number[]): Uint8Array => {
    const out = new Uint8Array(samples.length * 2);
    samples.forEach((s, i) => {
      out[i * 2] = s & 0xff;
      out[i * 2 + 1] = (s >> 8) & 0xff;
    });
    return out;
  };

  it('0 解码为 0', () => {
    const d = createPcmStreamDecoder();
    expect(Array.from(d.push(le(0)))).toEqual([0]);
  });

  it('正的满量程 32767 解出接近 +1', () => {
    const d = createPcmStreamDecoder();
    expect(d.push(le(32767))[0]).toBeCloseTo(32767 / 32768, 6);
  });

  it('负数正确做符号扩展（不能变成大正数）', () => {
    const d = createPcmStreamDecoder();
    // 0xFFFF = -1，若漏了符号扩展会得到 65535/32768 ≈ 2.0
    expect(d.push(le(-1))[0]).toBeCloseTo(-1 / 32768, 6);
  });

  it('负的满量程 -32768 解出 -1', () => {
    const d = createPcmStreamDecoder();
    expect(d.push(le(-32768))[0]).toBeCloseTo(-1, 6);
  });

  it('空分片返回空，不抛异常', () => {
    const d = createPcmStreamDecoder();
    expect(d.push(new Uint8Array(0)).length).toBe(0);
  });

  it('多个样本按顺序解出', () => {
    const d = createPcmStreamDecoder();
    const out = d.push(le(100, -100, 32767, -32768));
    expect(out.length).toBe(4);
    expect(out[0]).toBeCloseTo(100 / 32768, 6);
    expect(out[1]).toBeCloseTo(-100 / 32768, 6);
  });

  it('样本被切在分片边界上时不错位', () => {
    // 关键用例：把一个样本的两个字节拆到两片里
    const whole = le(1000, -2000, 3000);
    const first = whole.subarray(0, 3);   // 1.5 个样本
    const second = whole.subarray(3);     // 剩下 1.5 个

    const d = createPcmStreamDecoder();
    const a = d.push(first);
    const b = d.push(second);

    expect(a.length).toBe(1);             // 只解出第一个，半个留着
    expect(b.length).toBe(2);             // 下一片补齐后解出剩下两个

    const all = [...Array.from(a), ...Array.from(b)];
    expect(all[0]).toBeCloseTo(1000 / 32768, 6);
    expect(all[1]).toBeCloseTo(-2000 / 32768, 6);
    expect(all[2]).toBeCloseTo(3000 / 32768, 6);
  });

  it('逐字节喂入也能正确还原（最极端的分片）', () => {
    const whole = le(12345, -12345, 32767, -32768, 0);
    const d = createPcmStreamDecoder();
    const collected: number[] = [];
    for (let i = 0; i < whole.length; i++) {
      collected.push(...Array.from(d.push(whole.subarray(i, i + 1))));
    }
    expect(collected.length).toBe(5);
    expect(collected[0]).toBeCloseTo(12345 / 32768, 6);
    expect(collected[1]).toBeCloseTo(-12345 / 32768, 6);
    expect(collected[2]).toBeCloseTo(32767 / 32768, 6);
    expect(collected[3]).toBeCloseTo(-1, 6);
    expect(collected[4]).toBe(0);
  });

  it('两个解码器实例的进位状态互不干扰', () => {
    const a = createPcmStreamDecoder();
    const b = createPcmStreamDecoder();
    a.push(new Uint8Array([0x01]));       // a 留了半个样本
    // b 应该当作全新的流，不受 a 的进位影响
    expect(Array.from(b.push(le(0)))).toEqual([0]);
  });
});
