import { useState, useCallback, useRef, useEffect } from 'react';
import { Platform } from 'react-native';

interface UseASROptions {
  onTranscript?: (text: string, isFinal: boolean, emotion?: any) => void;
  onStatusChange?: (status: 'idle' | 'listening' | 'processing' | 'reconnecting') => void;
  onError?: (message: string) => void;
  wsUrl?: string;
}

export const useASR = ({ onTranscript, onStatusChange, onError, wsUrl = 'ws://localhost:8050/ws/asr' }: UseASROptions) => {
  const [status, setStatus] = useState<'idle' | 'listening' | 'processing' | 'reconnecting'>('idle');
  const [isRecording, setIsRecording] = useState(false);
  
  // Ref for echo cancellation state
  const isTTSMutedRef = useRef(false);
  const unmuteTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Ref to suppress onclose/onerror error toast when close is user-initiated
  const isIntentionalCloseRef = useRef(false);

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stop = useCallback(() => {
    setIsRecording(false);
    setStatus('idle');
    onStatusChange?.('idle');

    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (analyserRef.current) {
      analyserRef.current.disconnect();
      analyserRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    if (wsRef.current) {
      console.log('[useASR.stop] User-initiated close, setting intentional flag');
      isIntentionalCloseRef.current = true;
      // Null out handlers to prevent stale onclose/onerror (from pre-hot-reload)
      // from firing and showing false error toasts
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
      // Reset flag after onclose fires (async), so future connections aren't affected
      setTimeout(() => { isIntentionalCloseRef.current = false; }, 0);
    } else {
      console.log('[useASR.stop] wsRef is null, flag NOT set');
    }
  }, [onStatusChange]);

  const start = useCallback(async (sessionId: string) => {
    if (Platform.OS !== 'web') {
      console.warn('Real-time audio capture is currently optimized for Web/Laptop testing.');
      return;
    }

    try {
      // Reset intentional close flag for new connection
      isIntentionalCloseRef.current = false;

      // 1. Setup WebSocket
      // 带上 session_id，使后端的情绪历史与 LLM 的对话历史落在同一个会话键上
      wsRef.current = new WebSocket(`${wsUrl}?session_id=${encodeURIComponent(sessionId)}`);
      wsRef.current.onopen = () => {
        setStatus('listening');
        onStatusChange?.('listening');
        setIsRecording(true);
      };
      
      wsRef.current.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'transcript') {
          // 中间结果：更新 interim 文本（实时显示正在说的文字）
          if (!data.is_final) {
            onTranscript?.(data.text, false, undefined);
            return;
          }
          onTranscript?.(data.text, data.is_final, data.emotion);
        } else if (data.type === 'status') {
          setStatus(data.state);
          onStatusChange?.(data.state);
        }
      };

      wsRef.current.onclose = (e) => {
        console.log('[useASR.onclose] code=' + e.code + ', intentional=' + isIntentionalCloseRef.current + ', wasClean=' + e.wasClean);
        // code 1000 = normal, otherwise unexpected
        // Skip error toast if close was user-initiated (intentional hangup)
        if (e.code !== 1000 && !isIntentionalCloseRef.current) {
          console.log('[useASR.onclose] SHOWING error toast');
          onError?.('网络连接中断，请再试一次');
        } else {
          console.log('[useASR.onclose] Error suppressed (code=' + e.code + ' or intentional)');
        }
        stop();
      };
      wsRef.current.onerror = () => {
        console.log('[useASR.onerror] intentional=' + isIntentionalCloseRef.current);
        // Skip error toast if close was user-initiated
        if (!isIntentionalCloseRef.current) {
          console.log('[useASR.onerror] SHOWING error toast');
          onError?.('网络连接中断，请再试一次');
        } else {
          console.log('[useASR.onerror] Error suppressed (intentional)');
        }
        stop();
      };

      // 2. Setup Audio Capture (Web)
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: { 
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true
        } 
      });
      streamRef.current = stream;

      const audioContext = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);
      
      // Setup Analyser
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.8;
      analyserRef.current = analyser;

      const processor = audioContext.createScriptProcessor(2048, 1, 1); // ~128ms frames
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        // Echo Cancellation check
        if (isTTSMutedRef.current) return;

        if (wsRef.current?.readyState === WebSocket.OPEN) {
          const inputData = e.inputBuffer.getChannelData(0);
          // Convert Float32 to Int16
          const pcmData = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            pcmData[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32768));
          }
          wsRef.current.send(pcmData.buffer);
        }
      };

      source.connect(analyser);
      analyser.connect(processor);
      processor.connect(audioContext.destination);

    } catch (err) {
      console.error('Failed to start ASR:', err);
      stop();
    }
  }, [onStatusChange, onTranscript, stop, wsUrl]);

  // Setup Global Event Listeners for TTS Echo Cancellation
  useEffect(() => {
    const handleTTSStart = () => {
      isTTSMutedRef.current = true;
      if (unmuteTimeoutRef.current) {
        clearTimeout(unmuteTimeoutRef.current);
        unmuteTimeoutRef.current = null;
      }
      console.log('[useASR] Muted (TTS Active)');
    };

    const handleTTSEnd = () => {
      // 200ms delay to allow room reverb to dissipate
      unmuteTimeoutRef.current = setTimeout(() => {
        isTTSMutedRef.current = false;
        unmuteTimeoutRef.current = null;
        console.log('[useASR] Unmuted (200ms Delay Passed)');
      }, 200);
    };

    window.addEventListener('tts-start', handleTTSStart);
    window.addEventListener('tts-end', handleTTSEnd);

    return () => {
      window.removeEventListener('tts-start', handleTTSStart);
      window.removeEventListener('tts-end', handleTTSEnd);
      if (unmuteTimeoutRef.current) clearTimeout(unmuteTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    return () => stop();
  }, [stop]);

  return { start, stop, status, isRecording, analyser: analyserRef.current };
};
