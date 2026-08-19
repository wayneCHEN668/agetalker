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
export const floatToInt16 = (samples: Float32Array): Int16Array<ArrayBuffer> => {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    out[i] = Math.max(-32768, Math.min(32767, samples[i] * 32768));
  }
  return out;
};
