import { useState, useCallback, useRef } from 'react';
import { TTS_CONFIG, TTSParams } from '../constants/TTS';

interface QueueItem {
  text: string;
  ttsParams: TTSParams;
  emotionLabel: string;
}

interface UseTTSOptions {
  apiBase?: string;
  onPlaybackDone?: () => void;
}

export const useTTS = (options: UseTTSOptions = {}) => {
  const { apiBase = TTS_CONFIG.BASE_URL, onPlaybackDone } = options;
  const [isPlaying, setIsPlaying] = useState(false);

  // WebAudio refs
  const audioCtxRef = useRef<AudioContext | null>(null);
  const nextStartTimeRef = useRef<number>(0);

  // Queue state
  const playQueueRef = useRef<QueueItem[]>([]);
  const isProcessingRef = useRef(false);

  /**
   * Initialize or resume AudioContext
   */
  const initAudio = useCallback(() => {
    if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
      audioCtxRef.current = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: TTS_CONFIG.SAMPLE_RATE,
      });
      nextStartTimeRef.current = audioCtxRef.current.currentTime;
    }
    if (audioCtxRef.current.state === 'suspended') {
      audioCtxRef.current.resume();
    }
    return audioCtxRef.current;
  }, []);

  /**
   * Play a single sentence by fetching PCM stream.
   * Uses backend-computed ttsParams directly (single source of truth).
   */
  const playOnce = async (text: string, ttsParams: TTSParams, emotionLabel: string) => {
    const ctx = initAudio();

    try {
      const response = await fetch(`${apiBase}/tts/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          speed: ttsParams.speed,
          pitch: ttsParams.pitch,
          style: ttsParams.style,
          emotion_label: emotionLabel,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`TTS Fetch failed: ${response.status}`);
      }

      const reader = response.body.getReader();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        // Convert Uint8Array (PCM 16bit) to Float32 for WebAudio
        const int16Buffer = new Int16Array(value.buffer, value.byteOffset, value.byteLength / 2);
        const float32Buffer = new Float32Array(int16Buffer.length);
        for (let i = 0; i < int16Buffer.length; i++) {
          float32Buffer[i] = int16Buffer[i] / 32768.0;
        }

        // Create AudioBuffer
        const audioBuffer = ctx.createBuffer(1, float32Buffer.length, TTS_CONFIG.SAMPLE_RATE);
        audioBuffer.getChannelData(0).set(float32Buffer);

        // Schedule playback
        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);

        const startTime = Math.max(ctx.currentTime, nextStartTimeRef.current);
        source.start(startTime);
        nextStartTimeRef.current = startTime + audioBuffer.duration;
      }

      // Wait for the scheduled audio to finish
      const waitTime = (nextStartTimeRef.current - ctx.currentTime) * 1000;
      if (waitTime > 0) {
        await new Promise(resolve => setTimeout(resolve, waitTime));
      }

    } catch (err) {
      console.error('[useTTS] Error playing sentence:', err);
    }
  };

  /**
   * Process the queue sequentially
   */
  const processQueue = async () => {
    if (isProcessingRef.current) return;
    isProcessingRef.current = true;
    setIsPlaying(true);

    window.dispatchEvent(new CustomEvent('tts-start'));

    while (playQueueRef.current.length > 0) {
      const item = playQueueRef.current.shift()!;
      await playOnce(item.text, item.ttsParams, item.emotionLabel);
    }

    isProcessingRef.current = false;
    setIsPlaying(false);

    window.dispatchEvent(new CustomEvent('tts-end'));
    onPlaybackDone?.();
  };

  /**
   * Public API: Queue a sentence for speaking.
   * ttsParams comes from the backend LLM done event (single source of truth).
   */
  const speak = useCallback((
    text: string,
    ttsParams: TTSParams = { speed: 1.0, pitch: 0, style: 'neutral' },
    emotionLabel: string = 'neutral'
  ) => {
    if (!text.trim()) return;
    playQueueRef.current.push({ text, ttsParams, emotionLabel });
    processQueue();
  }, []);

  /**
   * Stop all playback and clear queue
   */
  const stop = useCallback(() => {
    playQueueRef.current = [];
    if (audioCtxRef.current) {
      audioCtxRef.current.close();
      audioCtxRef.current = null;
    }
    setIsPlaying(false);
    isProcessingRef.current = false;
    window.dispatchEvent(new CustomEvent('tts-end'));
  }, []);

  return { speak, stop, isPlaying };
};
