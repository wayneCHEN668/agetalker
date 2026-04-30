import { useState, useCallback, useRef, useEffect } from 'react';
import { Platform } from 'react-native';

interface UseASROptions {
  onTranscript?: (text: string, isFinal: boolean) => void;
  onStatusChange?: (status: 'idle' | 'listening' | 'processing') => void;
  wsUrl?: string;
}

export const useASR = ({ onTranscript, onStatusChange, wsUrl = 'ws://localhost:8050/ws/asr' }: UseASROptions) => {
  const [status, setStatus] = useState<'idle' | 'listening' | 'processing'>('idle');
  const [isRecording, setIsRecording] = useState(false);
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
      wsRef.current.close();
      wsRef.current = null;
    }
  }, [onStatusChange]);

  const start = useCallback(async () => {
    if (Platform.OS !== 'web') {
      console.warn('Real-time audio capture is currently optimized for Web/Laptop testing.');
      return;
    }

    try {
      // 1. Setup WebSocket
      wsRef.current = new WebSocket(wsUrl);
      wsRef.current.onopen = () => {
        setStatus('listening');
        onStatusChange?.('listening');
        setIsRecording(true);
      };
      
      wsRef.current.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'transcript') {
          onTranscript?.(data.text, data.is_final);
        } else if (data.type === 'status') {
          setStatus(data.state);
          onStatusChange?.(data.state);
        }
      };

      wsRef.current.onclose = () => stop();
      wsRef.current.onerror = (err) => {
        console.error('WebSocket Error:', err);
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

  useEffect(() => {
    return () => stop();
  }, [stop]);

  return { start, stop, status, isRecording, analyser: analyserRef.current };
};
