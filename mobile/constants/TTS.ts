/**
 * TTS Module Constants (STEP 4)
 * 
 * Implements "Healing Symmetry" - mapping user emotions to therapeutic AI voice styles.
 */

export interface TTSParams {
  speed: number;
  pitch: number;
  style: string;
}

export const TTS_PARAMS_MAP: Record<string, TTSParams> = {
  sad:       { speed: 0.85, pitch: -2, style: 'gentle' },
  fearful:   { speed: 0.88, pitch: -1, style: 'calm' },
  angry:     { speed: 0.88, pitch: -1, style: 'gentle' },
  happy:     { speed: 1.05, pitch: 1,  style: 'cheerful' },
  disgusted: { speed: 0.92, pitch: -1, style: 'calm' },
  surprised: { speed: 1.00, pitch: 0,  style: 'neutral' },
  neutral:   { speed: 1.00, pitch: 0,  style: 'neutral' },
  _crisis:   { speed: 0.82, pitch: -2, style: 'gentle' },
};

export const DEFAULT_TTS_PARAMS: TTSParams = TTS_PARAMS_MAP.neutral;

export const TTS_CONFIG = {
  SAMPLE_RATE: 24000,
  CHANNELS: 1,
  BIT_DEPTH: 16,
  BASE_URL: 'http://localhost:8050',
};
