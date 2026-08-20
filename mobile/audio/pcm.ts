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

/**
 * 流式 16 位小端 PCM 解码器（后端 TTS 那条流的反向操作）。
 *
 * 之所以要有状态：一个样本占 2 字节，而流式分片的边界是任意的，完全可能切在样本
 * 中间。实测 expo/fetch 在 Android 上就会给出零长度分片，而它底层（okio 缓冲区）
 * 也不保证每片都是偶数字节。不接住跨片的那半个样本，从该处起整段音频会整体错位
 * 一个字节——听感上就是噪声。
 *
 * 用法：每片调一次 push()，返回这一片能解出来的样本；不足半个样本的尾巴会留到
 * 下一次调用。
 */
export const createPcmStreamDecoder = () => {
  let carryByte: number | null = null;

  return {
    push(chunk: Uint8Array): Float32Array {
      // 拼上上一片留下的半个样本
      let bytes: Uint8Array;
      if (carryByte === null) {
        bytes = chunk;
      } else {
        bytes = new Uint8Array(chunk.byteLength + 1);
        bytes[0] = carryByte;
        bytes.set(chunk, 1);
        carryByte = null;
      }

      // 奇数字节：末尾那个留到下一片
      if (bytes.byteLength % 2 !== 0) {
        carryByte = bytes[bytes.byteLength - 1];
        bytes = bytes.subarray(0, bytes.byteLength - 1);
      }

      const out = new Float32Array(bytes.byteLength / 2);
      for (let i = 0; i < out.length; i++) {
        // 手工组小端并做符号扩展：bytes 可能来自 subarray 或拼接，byteOffset 不保证
        // 2 字节对齐，直接 new Int16Array(buffer, offset, len) 会因对齐要求抛 RangeError。
        const raw = bytes[i * 2] | (bytes[i * 2 + 1] << 8);
        out[i] = ((raw << 16) >> 16) / 32768.0;
      }
      return out;
    },
  };
};
