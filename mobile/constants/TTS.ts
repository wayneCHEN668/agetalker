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
