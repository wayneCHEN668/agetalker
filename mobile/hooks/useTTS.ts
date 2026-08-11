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
  // 与 isPlaying 同步的 ref：state 在回调闭包里会读到旧值，
  // 调用方需要一个「此刻是否还在放」的可靠读法
  const isPlayingRef = useRef(false);

  // WebAudio refs
  const audioCtxRef = useRef<AudioContext | null>(null);
  const nextStartTimeRef = useRef<number>(0);

  // Queue state
  const playQueueRef = useRef<QueueItem[]>([]);
  const isProcessingRef = useRef(false);

  // ─── 打断相关 ────────────────────────────────────────────────────────────
  // 本轮回复的播放时间线：每段文本被排在哪个时间窗内播。
  // 打断时拿它按当前时刻算出「已经真正播出去多少」，去截断后端的对话历史——
  // 否则模型以为自己说完了整段，下一轮可能引用老人根本没听到的内容。
  const scheduleRef = useRef<{ text: string; startTime: number; endTime: number }[]>([]);
  // 已排期但还没播完的源节点。急停时逐个 stop——不能靠关 AudioContext，
  // 打断是高频操作，反复关闭重建又慢、某些浏览器还有实例数上限。
  const scheduledSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  // 播放世代号：打断后自增，让还在 await 的旧 playOnce 认出自己已经作废，
  // 不要再把整段文本记成"已播出"
  const epochRef = useRef(0);

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
   * 取一段文本的 PCM 并排进播放时间线。
   *
   * 关键：这里**不等音频播完**。原先的实现取完一段就 await 到它播放结束，
   * 才去取下一段——于是下一段的合成延迟（网络往返 + CosyVoice 会话启动，
   * 约 300~800ms）会原封不动地暴露成句间空白，听上去就是「一句一句往外蹦、
   * 中间还卡顿」。
   *
   * 现在取完立刻返回，下一段的请求马上发出去；排期交给 nextStartTimeRef，
   * WebAudio 会把先后两段严丝合缝地接起来，句间没有空隙。
   */
  const fetchAndSchedule = async (text: string, ttsParams: TTSParams, emotionLabel: string) => {
    const ctx = initAudio();
    const epoch = epochRef.current;
    let chunkStart: number | null = null;

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
        if (epoch !== epochRef.current) return;   // 已被打断，别再排新的了

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

        if (chunkStart === null) chunkStart = startTime;

        // 持有引用以便急停；自然播完后自己摘掉，避免长会话里越积越多
        scheduledSourcesRef.current.push(source);
        source.onended = () => {
          const arr = scheduledSourcesRef.current;
          const i = arr.indexOf(source);
          if (i >= 0) arr.splice(i, 1);
        };
      }

      // 记下这一段被排在哪个时间窗内播，供打断时算「说到哪儿了」
      if (epoch === epochRef.current && chunkStart !== null) {
        scheduleRef.current.push({
          text,
          startTime: chunkStart,
          endTime: nextStartTimeRef.current,
        });
      }

    } catch (err) {
      console.error('[useTTS] Error playing sentence:', err);
    }
  };

  /** 等到已排期的音频全部放完。 */
  const waitUntilScheduleEnd = async () => {
    const ctx = audioCtxRef.current;
    if (!ctx) return;
    const remainMs = (nextStartTimeRef.current - ctx.currentTime) * 1000;
    if (remainMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, remainMs));
    }
  };

  /**
   * Process the queue sequentially
   */
  const processQueue = async () => {
    if (isProcessingRef.current) return;
    isProcessingRef.current = true;
    isPlayingRef.current = true;
    setIsPlaying(true);

    window.dispatchEvent(new CustomEvent('tts-start'));
    const epoch = epochRef.current;

    // 内层：把队列里的文本尽快全部取回来并排期（互相之间不等播放）
    // 外层：排完之后等音频放完；等的期间要是又有新句子进来，回到内层继续
    while (true) {
      while (playQueueRef.current.length > 0 && epoch === epochRef.current) {
        const item = playQueueRef.current.shift()!;
        await fetchAndSchedule(item.text, item.ttsParams, item.emotionLabel);
      }
      if (epoch !== epochRef.current) break;
      await waitUntilScheduleEnd();
      if (playQueueRef.current.length === 0) break;
    }

    // 被打断的话，状态已经由 haltAudio() 收拾过了，这里不要再覆盖一遍
    if (epoch !== epochRef.current) return;

    isProcessingRef.current = false;
    isPlayingRef.current = false;
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

  /** 清空队列并停掉所有已排期的音频（不动 AudioContext）。 */
  const haltAudio = useCallback(() => {
    epochRef.current += 1;            // 让还在 await 的旧 playOnce 作废
    playQueueRef.current = [];
    scheduledSourcesRef.current.forEach((s) => {
      try { s.onended = null; s.stop(); } catch { /* 已经停了 */ }
    });
    scheduledSourcesRef.current = [];
    if (audioCtxRef.current) {
      nextStartTimeRef.current = audioCtxRef.current.currentTime;
    }
    isPlayingRef.current = false;
    isProcessingRef.current = false;
    setIsPlaying(false);
  }, []);

  /**
   * 老人插话时的急停。
   *
   * 与 stop() 的区别：**不关闭 AudioContext**。打断是高频操作，反复关闭重建
   * 又慢、某些浏览器还有实例数上限；这里只把已排期的源节点停掉，上下文留着复用。
   */
  const stopForBargeIn = useCallback(() => {
    haltAudio();
    window.dispatchEvent(new CustomEvent('tts-end'));
  }, [haltAudio]);

  /**
   * 到目前为止**真正播出去**的文本。
   *
   * 已完整播完的段落全算，正在播的那一段按「已播时长 / 总时长」的比例取前面
   * 一部分字符（中文 TTS 语速基本恒定，这个估算够用）。
   * 被打断时拿它去截断后端历史，模型才不会引用老人没听到的内容。
   */
  const getSpokenText = useCallback(() => {
    const ctx = audioCtxRef.current;
    if (!ctx) return '';
    const now = ctx.currentTime;
    let spoken = '';
    for (const seg of scheduleRef.current) {
      if (now >= seg.endTime) {          // 这一段整个放完了
        spoken += seg.text;
        continue;
      }
      if (now <= seg.startTime) break;   // 还没轮到它，后面的更不用看
      const span = seg.endTime - seg.startTime;
      const ratio = span > 0 ? (now - seg.startTime) / span : 0;
      spoken += seg.text.slice(0, Math.floor(seg.text.length * ratio));
      break;
    }
    return spoken;
  }, []);

  /** 新一轮回复开始前调用，清空上一轮的播放时间线。 */
  const resetSpokenText = useCallback(() => {
    scheduleRef.current = [];
  }, []);

  /**
   * 彻底停止（结束会话时用）。除了停音频，还关掉 AudioContext 释放设备。
   */
  const stop = useCallback(() => {
    haltAudio();
    if (audioCtxRef.current) {
      audioCtxRef.current.close();
      audioCtxRef.current = null;
    }
    window.dispatchEvent(new CustomEvent('tts-end'));
  }, [haltAudio]);

  return {
    speak, stop, stopForBargeIn, getSpokenText, resetSpokenText,
    isPlaying, isPlayingRef,
  };
};
