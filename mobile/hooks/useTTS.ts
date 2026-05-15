import { useState, useCallback, useRef } from 'react';
import { TTS_CONFIG, TTS_PARAMS_MAP, DEFAULT_TTS_PARAMS } from '../constants/TTS';

export interface UseTTSOptions {
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
  const playQueueRef = useRef<{ text: string; emotion: string }[]>([]);
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
   * Play a single sentence by fetching PCM stream
   */
  const playOnce = async (text: string, emotion: string) => {
    const ctx = initAudio();
    const params = TTS_PARAMS_MAP[emotion] || DEFAULT_TTS_PARAMS;

    try {
      const response = await fetch(`${apiBase}/tts/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          speed: params.speed,
          pitch: params.pitch,
          style: params.style,
          emotion_label: emotion,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`TTS Fetch failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      
      // We read chunks and decode them as Int16 PCM
      // Note: For simplicity and low latency, we schedule small chunks immediately
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

        // Calculate timing to ensure seamless stitching
        const startTime = Math.max(ctx.currentTime, nextStartTimeRef.current);
        source.start(startTime);
        nextStartTimeRef.current = startTime + audioBuffer.duration;
      }

      // Wait for the scheduled audio to finish before resolving this sentence
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

    // Emit event to mute ASR
    window.dispatchEvent(new CustomEvent('tts-start'));

    while (playQueueRef.current.length > 0) {
      const item = playQueueRef.current.shift()!;
      await playOnce(item.text, item.emotion);
    }

    isProcessingRef.current = false;
    setIsPlaying(false);

    // Emit event to unmute ASR (ASR module will add the 200ms delay)
    window.dispatchEvent(new CustomEvent('tts-end'));
    onPlaybackDone?.();
  };

  /**
   * Public API: Queue a sentence for speaking
   */
  const speak = useCallback((text: string, emotion: string = 'neutral') => {
    if (!text.trim()) return;
    playQueueRef.current.push({ text, emotion });
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
