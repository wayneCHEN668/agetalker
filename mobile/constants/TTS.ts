/**
 * TTS Module Constants (STEP 4)
 *
 * TTS parameters (speed/pitch/style) are now determined by the backend
 * LLMService and delivered via the SSE done event. The frontend no longer
 * maintains a duplicate TTS_PARAMS_MAP — the backend is the single source
 * of truth for healing-symmetry parameter selection.
 */

export interface TTSParams {
  speed: number;
  pitch: number;
  style: string;
}

export const TTS_CONFIG = {
  SAMPLE_RATE: 24000,
  CHANNELS: 1,
  BIT_DEPTH: 16,
  BASE_URL: 'http://localhost:8050',
};

/**
 * TTS 放完之后，麦克风还要静音多久才恢复收音（毫秒）——等房间混响散掉。
 *
 * 放在这里而不是写死在 useASR 里：主动招呼那条路径要等这段时间过完才能开麦，
 * 两边必须用同一个值，各写一个字面量迟早会对不上。
 */
export const TTS_UNMUTE_DELAY_MS = 200;
