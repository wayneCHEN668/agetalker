import { useState, useCallback, useRef, useEffect } from 'react';
import { DeviceEventEmitter, Platform } from 'react-native';
import { BARGE_IN } from '../constants/BargeIn';
import { TTS_UNMUTE_DELAY_MS } from '../constants/TTS';
import { WS_BASE_URL } from '../constants/Api';
import { computeRms, floatToInt16 } from '../audio/pcm';
import { ASR_FRAME_SAMPLES, ASR_SAMPLE_RATE } from '../constants/ASR';

interface UseASROptions {
  onTranscript?: (text: string, isFinal: boolean, emotion?: any) => void;
  onStatusChange?: (status: 'idle' | 'listening' | 'processing' | 'reconnecting') => void;
  onError?: (message: string) => void;
  /** 检测到老人在 TTS 播放期间插话。调用方应据此停掉 TTS 并截断历史。 */
  onBargeIn?: () => void;
  wsUrl?: string;
}

export const useASR = ({ onTranscript, onStatusChange, onError, onBargeIn, wsUrl = `${WS_BASE_URL}/ws/asr` }: UseASROptions) => {
  const [status, setStatus] = useState<'idle' | 'listening' | 'processing' | 'reconnecting'>('idle');
  const [isRecording, setIsRecording] = useState(false);

  // Ref for echo cancellation state
  const isTTSMutedRef = useRef(false);
  const unmuteTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ─── 打断检测状态 ────────────────────────────────────────────────────────
  // TTS 期间麦克风帧不发往云端（防回声自问自答），但仍在本地过能量检测。
  const ttsStartedAtRef = useRef(0);
  const baselineRmsRef = useRef<number[]>([]);   // 开头一小段的底噪采样
  const thresholdRef = useRef(0);                // 由底噪算出的判定阈值
  const sustainedRef = useRef(0);                // 连续超阈值的帧数
  // 预缓冲：静音期最近若干帧。检测本身要花几帧时间，没有它老人开口的头几个字
  // 会被吃掉——打断成立时先把这些补发给云端。
  const preBufferRef = useRef<ArrayBuffer[]>([]);
  const onBargeInRef = useRef(onBargeIn);
  onBargeInRef.current = onBargeIn;

  /** 重置一轮 TTS 的打断检测状态。 */
  const resetBargeInState = useCallback(() => {
    ttsStartedAtRef.current = Date.now();
    baselineRmsRef.current = [];
    thresholdRef.current = 0;
    sustainedRef.current = 0;
    preBufferRef.current = [];
  }, []);

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
          sampleRate: ASR_SAMPLE_RATE,
          channelCount: 1,
          echoCancellation: true
        } 
      });
      streamRef.current = stream;

      const audioContext = new AudioContext({ sampleRate: ASR_SAMPLE_RATE });
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);
      
      // Setup Analyser
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.8;
      analyserRef.current = analyser;

      const processor = audioContext.createScriptProcessor(ASR_FRAME_SAMPLES, 1, 1); // ~128ms frames
      processorRef.current = processor;

      const sendFrame = (buf: ArrayBuffer) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(buf);
        }
      };

      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        const pcmData = floatToInt16(inputData);

        // 正常收音
        if (!isTTSMutedRef.current) {
          sendFrame(pcmData.buffer);
          return;
        }

        // ── TTS 播放期间：不往云端发（防回声），但本地判断有没有人在插话 ──
        const pre = preBufferRef.current;
        pre.push(pcmData.buffer);
        if (pre.length > BARGE_IN.PREBUFFER_FRAMES) pre.shift();

        if (!BARGE_IN.ENABLED) return;

        const elapsed = Date.now() - ttsStartedAtRef.current;
        const rms = computeRms(inputData);

        // 阶段一：测环境底噪。浏览器 AEC 已经把喇叭声消掉大半，
        // 这时候的读数基本就是房间本底。
        if (elapsed < BARGE_IN.BASELINE_MS) {
          baselineRmsRef.current.push(rms);
          return;
        }

        // 阶段二：底噪采完，算一次阈值
        if (thresholdRef.current === 0) {
          const samples = baselineRmsRef.current;
          const mean = samples.length
            ? samples.reduce((a, b) => a + b, 0) / samples.length
            : 0;
          thresholdRef.current = Math.max(
            mean * BARGE_IN.THRESHOLD_RATIO,
            BARGE_IN.MIN_THRESHOLD_RMS,
          );
          console.log(
            `[BargeIn] 底噪=${mean.toFixed(4)} 阈值=${thresholdRef.current.toFixed(4)}`,
          );
        }

        // 保护期内不判打断，避免老人自己上一句的尾音把回复刚开头就掐掉
        if (elapsed < BARGE_IN.GRACE_MS) return;

        // 阶段三：连续超阈值才算，滤掉咳嗽/关门/电视里的单个爆音
        if (rms > thresholdRef.current) {
          sustainedRef.current += 1;
        } else {
          sustainedRef.current = 0;
          return;
        }
        if (sustainedRef.current < BARGE_IN.SUSTAINED_FRAMES) return;

        // ── 判定为插话 ──
        console.log(`[BargeIn] 检测到插话 (rms=${rms.toFixed(4)})`);
        isTTSMutedRef.current = false;      // 立刻恢复收音，不等 tts-end 的 200ms 去抖
        if (unmuteTimeoutRef.current) {
          clearTimeout(unmuteTimeoutRef.current);
          unmuteTimeoutRef.current = null;
        }
        // 先补发预缓冲，老人开口的头几个字才不会丢
        preBufferRef.current.forEach(sendFrame);
        preBufferRef.current = [];
        sustainedRef.current = 0;

        onBargeInRef.current?.();
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
      resetBargeInState();
      if (unmuteTimeoutRef.current) {
        clearTimeout(unmuteTimeoutRef.current);
        unmuteTimeoutRef.current = null;
      }
      console.log('[useASR] Muted (TTS Active)');
    };

    const handleTTSEnd = () => {
      preBufferRef.current = [];
      // 已经因为插话提前恢复收音了，不用再走这条路
      if (!isTTSMutedRef.current) return;
      // 200ms delay to allow room reverb to dissipate
      unmuteTimeoutRef.current = setTimeout(() => {
        isTTSMutedRef.current = false;
        unmuteTimeoutRef.current = null;
        console.log('[useASR] Unmuted (200ms Delay Passed)');
      }, TTS_UNMUTE_DELAY_MS);
    };

    const startSub = DeviceEventEmitter.addListener('tts-start', handleTTSStart);
    const endSub = DeviceEventEmitter.addListener('tts-end', handleTTSEnd);

    return () => {
      startSub.remove();
      endSub.remove();
      if (unmuteTimeoutRef.current) clearTimeout(unmuteTimeoutRef.current);
    };
  }, [resetBargeInState]);

  useEffect(() => {
    return () => stop();
  }, [stop]);

  return { start, stop, status, isRecording, analyser: analyserRef.current };
};
