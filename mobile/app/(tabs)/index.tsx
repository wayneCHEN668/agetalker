import React, { useState, useCallback, useRef, useEffect } from 'react';
import { StyleSheet, View, SafeAreaView, Text, TouchableOpacity } from 'react-native';
import { Design } from '@/constants/Design';
import { CATEGORY_ZH_MAP } from '@/constants/Category';
import {
  newSessionId, SILENCE_PROMPT_MS, PROACTIVE_SCHEDULE, PROACTIVE_NO_ANSWER_MS,
  PROACTIVE_PLAYBACK_WAIT_MAX_MS,
} from '@/constants/Session';
import { TTS_UNMUTE_DELAY_MS } from '@/constants/TTS';
import { getViewMode, setViewMode as persistViewMode, DEFAULT_VIEW_MODE, ViewMode } from '@/constants/ViewMode';
import { StatusBar } from '@/components/StatusBar';
import { TranscriptArea } from '@/components/TranscriptArea';
import { Waveform } from '@/components/Waveform';
import { OrbVisualizer, derivePhase } from '@/components/OrbVisualizer';
import { ActionButton } from '@/components/ActionButton';
import { ErrorToast } from '@/components/ErrorToast';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { ChatMessage } from '@/components/ChatBubble';

import { useASR } from '@/hooks/useASR';
import { useLLM } from '@/hooks/useLLM';
import { useTTS } from '@/hooks/useTTS';

export default function HomeScreen() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentEmotion, setCurrentEmotion] = useState('neutral');
  const [errorMessage, setErrorMessage] = useState('');
  const [showEndDialog, setShowEndDialog] = useState(false);
  const [isLLMStreaming, setIsLLMStreaming] = useState(false);
  // 抽象可视化 / 对话窗口。默认抽象，首帧先按默认值渲染，读存储回来前不会闪一下再变
  const [viewMode, setViewModeState] = useState<ViewMode>(DEFAULT_VIEW_MODE);

  // 跟踪流式 AI 消息在 messages 中的索引
  const streamingIndexRef = useRef<number | null>(null);

  // 本次对话的会话 ID：每次开始对话新生成，ASR / 情绪 / LLM 三处共用同一个键
  const sessionIdRef = useRef<string>('');

  // 正在走结束流程（收束告别播放中）。只有这个标志为真时，TTS 播放队列
  // 排空才意味着「该清屏了」——平时每轮回复播完也会排空，不能一概处理。
  const isEndingRef = useRef(false);
  // 告别的**文字**流是否已经结束（语音是否放完是另一个条件，见 finishEndSession）
  const closingTextDoneRef = useRef(false);
  const endFallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 用 ref 转一层：finishEndSession 依赖 stopTTS，而 stopTTS 来自 useTTS，
  // 直接互相引用会成环
  const onPlaybackDoneRef = useRef<() => void>(() => {});
  // 沉默唤起计时器。老人开着对话但一直没说话时，AI 先开口。
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 今天已经触发过的时间点（小时）。防止同一个整点内反复触发。
  const firedHoursRef = useRef<Set<string>>(new Set());
  const noAnswerTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 主动招呼之后，老人有没有搭话
  const proactiveAnsweredRef = useRef(false);
  // isRecording 的 ref 镜像。定时招呼要等语音放完（十几秒）才开麦，这段时间里
  // 闭包里的 isRecording 是陈旧的，不能拿它判断「现在是不是已经在录了」。
  const isRecordingRef = useRef(false);

  // 1. TTS
  const {
    speak, stop: stopTTS, stopForBargeIn, getSpokenText, resetSpokenText,
    isPlaying: ttsIsPlaying, isPlayingRef: ttsPlayingRef,
  } = useTTS({
    onPlaybackDone: () => onPlaybackDoneRef.current(),
  });

  // 2. LLM
  // 当前是否有一条回复正在生成（state 在回调里会读到旧值，用 ref）
  const replyInFlightRef = useRef(false);

  const {
    fetchReply, fetchClosing, fetchProactive, reportProactiveOutcome,
    abort: abortLLM, reset: resetLLM, isCrisis,
  } = useLLM({
    onDelta: (deltaText) => {
      setIsLLMStreaming(true);
      setMessages((prev) => {
        const idx = streamingIndexRef.current;
        if (idx !== null && idx < prev.length && prev[idx].role === 'assistant') {
          const updated = [...prev];
          updated[idx] = { ...updated[idx], text: prev[idx].text + deltaText };
          return updated;
        }
        // 第一条 delta：创建 AI 消息（替换 typing 指示器）
        const filtered = prev.filter((m) => !m.isInterim || m.role !== 'assistant');
        const msg: ChatMessage = { role: 'assistant', text: deltaText };
        const next = [...filtered, msg];
        streamingIndexRef.current = next.length - 1;
        return next;
      });
    },
    onSentence: (sentence, ttsParams, category) => {
      speak(sentence, ttsParams, category);

      const zh = CATEGORY_ZH_MAP[category] || category;
      setMessages((prev) => {
        for (let i = prev.length - 1; i >= 0; i--) {
          if (prev[i].role === 'user' && !prev[i].isInterim && !prev[i].category_zh) {
            const updated = [...prev];
            updated[i] = { ...updated[i], category_zh: zh };
            return updated;
          }
        }
        return prev;
      });
    },
    onDone: (strategyName) => {
      if (strategyName) {
        setMessages((prev) => {
          const idx = streamingIndexRef.current;
          if (idx !== null && idx < prev.length && prev[idx].role === 'assistant') {
            const updated = [...prev];
            updated[idx] = { ...updated[idx], strategyName };
            return updated;
          }
          return prev;
        });
      }
      streamingIndexRef.current = null;
      setIsLLMStreaming(false);
      replyInFlightRef.current = false;
      armSilenceTimer();
    },
  });

  /**
   * 作废正在进行中的那条回复。
   *
   * 触发场景：老人一句话被 ASR 切成了两段，第二段到达时第一条回复已经在生成
   * 或播放了。不作废的话两条回复都会发出来，而且内容常常大半重复——实测就是
   * 这个现象。这里把它就地掐掉，让下一次生成拿着完整的话重新说。
   */
  const discardOngoingReply = useCallback(async () => {
    if (!replyInFlightRef.current && !ttsPlayingRef.current) return;

    const spoken = getSpokenText();
    abortLLM();
    stopForBargeIn();
    replyInFlightRef.current = false;

    // 屏幕上那半条回复：说出口了就截断保留，一个字没说就整条撤掉
    setMessages((prev) => {
      const idx = streamingIndexRef.current;
      if (idx === null || idx >= prev.length || prev[idx].role !== 'assistant') return prev;
      const updated = [...prev];
      if (spoken.trim()) {
        updated[idx] = { ...updated[idx], text: spoken, interrupted: true };
      } else {
        updated.splice(idx, 1);
      }
      return updated;
    });
    streamingIndexRef.current = null;
    setIsLLMStreaming(false);

    // 必须等截断完成再发下一轮请求，否则新的用户消息先进历史，
    // 截断就找不到那条待处理的回复了
    try {
      await fetch(`http://localhost:8050/llm/truncate_last`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          spoken_text: spoken,
        }),
      });
    } catch (err) {
      console.warn('[HomeScreen] 截断历史失败:', err);
    }
  }, [abortLLM, stopForBargeIn, getSpokenText]);

  // 3. ASR
  const { start, stop: stopASR, status, isRecording, analyser } = useASR({
    onTranscript: async (text, isFinal, emotion) => {
      if (isFinal) {
        clearSilenceTimer();
        // 他搭话了：撤掉无人应答的收场计时
        if (noAnswerTimerRef.current) {
          clearTimeout(noAnswerTimerRef.current);
          noAnswerTimerRef.current = null;
          if (!proactiveAnsweredRef.current) {
            proactiveAnsweredRef.current = true;
            reportProactiveOutcome(true);
          }
        }
        // 老人又开口了：先把上一条还没说完的回复作废
        await discardOngoingReply();

        setMessages((prev) => {
          const filtered = prev.filter((m) => !m.isInterim);
          const userMsg: ChatMessage = {
            role: 'user',
            text,
            emotion,
          };
          return [...filtered, userMsg];
        });

        const emotionLabel = emotion?.label || 'neutral';
        setCurrentEmotion(emotionLabel);
        resetSpokenText();   // 新一轮回复开始，重置「已播出」的累计
        replyInFlightRef.current = true;
        fetchReply(text, emotion, sessionIdRef.current);
      } else {
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.isInterim) {
            const updated = [...prev];
            updated[updated.length - 1] = { ...last, text };
            return updated;
          }
          const interimMsg: ChatMessage = {
            role: 'user',
            text,
            isInterim: true,
          };
          return [...prev, interimMsg];
        });
      }
    },
    onError: (msg) => {
      setErrorMessage(msg);
    },
    /**
     * 老人在 AI 说话时插话：立刻停声让他说，并把历史截断到实际播出去的部分。
     *
     * 截断这一步不能省——历史里存的是完整回复，模型会以为自己整段说完了，
     * 下一轮可能引用老人根本没听到的后半截。
     */
    onBargeIn: () => {
      const spoken = getSpokenText();
      stopForBargeIn();

      // 把气泡里的文字也收到实际听到的位置，屏幕和耳朵保持一致
      setMessages((prev) => {
        const idx = streamingIndexRef.current;
        if (idx !== null && idx < prev.length && prev[idx].role === 'assistant') {
          const updated = [...prev];
          updated[idx] = { ...updated[idx], text: spoken, interrupted: true };
          return updated;
        }
        return prev;
      });
      streamingIndexRef.current = null;
      setIsLLMStreaming(false);

      fetch(`http://localhost:8050/llm/truncate_last`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          spoken_text: spoken,
        }),
      }).catch((err) => console.warn('[HomeScreen] 截断历史失败:', err));
    },
  });

  isRecordingRef.current = isRecording;

  const toggleConversation = useCallback(() => {
    if (isRecording) {
      clearSilenceTimer();
      // 停止录音 — 先确认
      if (messages.length > 0) {
        setShowEndDialog(true);
      } else {
        doEndSession();
      }
    } else {
      // 每次开始对话都用全新的 session_id，上一次对话的服务端状态不会残留过来
      const sessionId = newSessionId();
      sessionIdRef.current = sessionId;

      // 上一次的结束流程可能还没走完（告别还在播），这里作废掉，
      // 否则它的收尾清理会在新对话开始后触发、把刚说的话清掉
      isEndingRef.current = false;
      closingTextDoneRef.current = false;
      if (endFallbackTimerRef.current) {
        clearTimeout(endFallbackTimerRef.current);
        endFallbackTimerRef.current = null;
      }

      setMessages([]);
      setCurrentEmotion('neutral');
      streamingIndexRef.current = null;
      setIsLLMStreaming(false);
      setErrorMessage('');
      resetLLM();
      stopTTS();
      start(sessionId);
    }
  }, [isRecording, messages.length]);

  /**
   * 结束对话。
   *
   * 以前是「停掉一切 → 2.5 秒后把屏幕抹掉」。把一段哀伤或抑郁的叙事打开之后
   * 这样收场，临床上是有害的——不该把一个刚敞开心扉的人就这么晾在那儿。
   * 现在先播一段收束告别（回顾今天聊到的 → 肯定 → 道别 → 约定下次），
   * 等它说完再清屏。
   */
  /**
   * 告别真正说完之后的收尾清理。
   *
   * 必须同时满足两个条件才算「说完了」：
   * 1. 文字流结束（closingTextDoneRef）
   * 2. 语音队列播空（ttsPlayingRef 为 false）
   *
   * 只看其中一个都会出错：语音播放常常比 LLM 生成快，队列可能在两段文字之间
   * 就先空了一次，此时 onPlaybackDone 会提前触发——只看它就会把告别掐断在
   * 半截上。反过来只看文字流，则会在语音还剩十几秒时就清屏。
   * 所以这里做成幂等的，两个来源都调它，谁最后满足条件谁真正执行。
   */
  const finishEndSession = useCallback(() => {
    if (!isEndingRef.current) return;      // 不是在结束流程里（普通一轮播完）
    if (!closingTextDoneRef.current) return; // 文字还没流完
    if (ttsPlayingRef.current) return;       // 语音还在播

    isEndingRef.current = false;

    if (endFallbackTimerRef.current) {
      clearTimeout(endFallbackTimerRef.current);
      endFallbackTimerRef.current = null;
    }

    stopTTS();
    setMessages([]);
    setCurrentEmotion('neutral');
    streamingIndexRef.current = null;
    setIsLLMStreaming(false);
    // 传 sessionId：把本次摘要留档进长程台账，并释放会话级状态
    resetLLM(sessionIdRef.current);
  }, [resetLLM, stopTTS, ttsPlayingRef]);

  /** 清掉沉默计时器。任何"有动静"的地方都要调它。 */
  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  /**
   * 重新开始计时。
   *
   * 必须排除两个区间，否则 AI 会在自己刚说完的瞬间又开口：
   *   1. TTS 播放期间（ttsPlayingRef）
   *   2. LLM 生成期间（replyInFlightRef）
   * 这两个区间结束时会各自再调一次本函数，所以这里直接不排是安全的。
   */
  const armSilenceTimer = useCallback(() => {
    clearSilenceTimer();
    if (!isRecording || isEndingRef.current) return;
    if (ttsPlayingRef.current || replyInFlightRef.current) return;

    silenceTimerRef.current = setTimeout(async () => {
      // 触发的一刻再查一次：这段时间里可能已经开始播/开始生成了
      if (!isRecording || isEndingRef.current) return;
      if (ttsPlayingRef.current || replyInFlightRef.current) return;

      replyInFlightRef.current = true;
      const result = await fetchProactive(sessionIdRef.current, 'silence');
      // 被作废（老人在等待期间又开口了）：discardOngoingReply() 已经接管了
      // replyInFlightRef（先置 false 再为即将开始的真实回复置 true），这里
      // 不能再碰它，否则会把真实回复刚设的 true 冲掉。也不重新计时——
      // 是否要计时由真实回复流程自己决定。
      if (result?.reason !== 'aborted') {
        replyInFlightRef.current = false;

        // 没说出实际内容（被护栏拦下 / 生成失败）：安静收场，
        // 不重试、不提示老人，但要重新计时——过一会儿条件可能就满足了。
        if (!result?.fullText) armSilenceTimer();
      }
    }, SILENCE_PROMPT_MS);
  }, [isRecording, fetchProactive, clearSilenceTimer, ttsPlayingRef]);

  // start(sessionId) 不会同步更新 isRecording（state 更新是异步的），紧跟着直接
  // 调 armSilenceTimer 会读到还没更新的旧值、直接被守卫短路掉。改成响应式：
  // isRecording 真正变成 true 的那次渲染才去 arm。
  useEffect(() => {
    if (isRecording) armSilenceTimer();
  }, [isRecording, armSilenceTimer]);

  // 卸载时清掉沉默计时器
  useEffect(() => clearSilenceTimer, [clearSilenceTimer]);

  // 读取上次记住的展示模式（异步存储，读回来之前先按默认值渲染）
  useEffect(() => {
    let cancelled = false;
    getViewMode().then((mode) => {
      if (!cancelled) setViewModeState(mode);
    });
    return () => { cancelled = true; };
  }, []);

  const toggleViewMode = useCallback(() => {
    setViewModeState((prev) => {
      const next: ViewMode = prev === 'orb' ? 'chat' : 'orb';
      persistViewMode(next);
      return next;
    });
  }, []);

  /**
   * 等主动招呼的语音真正放完，再多等一下让 useASR 恢复收音。
   *
   * 为什么必须等：useASR 在 TTS 播放期间会把麦克风帧**整帧丢掉**（防止 AI 自己
   * 的声音被转成"用户说的话"）。这期间开麦等于开了个聋子——波形照抖（analyser
   * 挂在丢帧判断的前面），但一帧都到不了后端，后端是「收到第一帧才创建云端 ASR
   * 会话」，于是连会话都不会建。
   *
   * 为什么不能用 fetchProactive 返回当信号：它返回只代表**文字**流完了。一段
   * 招呼 LLM 三秒吐完，CosyVoice 还要再放十几秒——这正是原来失聪的那十几秒。
   *
   * 末尾还要多等 TTS_UNMUTE_DELAY_MS：useASR 收到 tts-end 之后还要再等这么久
   * （等混响散掉）才恢复收音，不等的话开麦的头几帧仍然会被丢掉。
   *
   * 返回 false 表示等超时了（TTS 请求挂死，播放标志再也不会翻回来）。这种情况
   * 下静音永远解不开，开麦只会得到一个聋子——所以调用方应当直接放弃这一轮。
   */
  const waitForPlaybackIdle = useCallback(async () => {
    const deadline = Date.now() + PROACTIVE_PLAYBACK_WAIT_MAX_MS;
    while (ttsPlayingRef.current && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (ttsPlayingRef.current) return false;
    await new Promise((resolve) => setTimeout(resolve, TTS_UNMUTE_DELAY_MS + 100));
    return true;
  }, [ttsPlayingRef]);

  /**
   * 定时主动招呼。
   *
   * 每分钟查一次表，到点且当前没有进行中的对话就自动开一个会话、AI 先说话、
   * 等语音放完再自动开麦。
   *
   * 错过不补发（设计文档 §9）：App 在后台或设备休眠时错过的时间点直接跳过，
   * 否则回前台会一次性说三段话。firedHoursRef 用「日期+小时」做键，天然满足
   * 这一点——过了那个小时就再也不会触发。
   */
  useEffect(() => {
    const tick = async () => {
      if (isRecording || isEndingRef.current) return;

      const now = new Date();
      const key = `${now.toDateString()}#${now.getHours()}`;
      if (!PROACTIVE_SCHEDULE.includes(now.getHours())) return;
      if (firedHoursRef.current.has(key)) return;
      firedHoursRef.current.add(key);

      const sessionId = newSessionId();
      sessionIdRef.current = sessionId;
      setMessages([]);
      setCurrentEmotion('neutral');
      setErrorMessage('');
      proactiveAnsweredRef.current = false;

      const result = await fetchProactive(sessionId, 'scheduled');
      // 被护栏拦下（夜间静默/每日上限/连续无应答）：安静收场，什么都不做
      if (result?.blocked || !result?.fullText) return;

      // 语音放完之前开麦是听不见的，见 waitForPlaybackIdle 的说明。
      // 超时说明 TTS 挂了，静音解不开——安静收场，也不上报无应答：
      // 这次是我们自己的链路坏了，不该算在老人头上去累加放弃计数。
      if (!await waitForPlaybackIdle()) return;

      // 等的这十几秒里老人可能自己按了按钮开了对话。再开一次会把那条 WebSocket
      // 和 MediaStream 直接冲掉（useASR.start 不做自检），旧连接的 onclose
      // 随后又会把新会话一起停掉。
      if (isRecordingRef.current || isEndingRef.current) return;

      // 说完了自动开麦，等他搭话。无人应答的倒计时也从这一刻起算——从文字流
      // 结束就起算的话，二十秒里有十几秒耗在放语音上，老人根本来不及应。
      start(sessionId);
      armNoAnswerTimer();
    };

    const id = setInterval(tick, 60_000);
    tick();
    return () => clearInterval(id);
  }, [isRecording, fetchProactive, start, waitForPlaybackIdle]);

  /**
   * 无人应答收场。
   *
   * 定时招呼时老人很可能不在。等一个窗口没人搭话就安静停掉、上报服务端；
   * 连续几次之后服务端当天不再主动开口——没有这条，设备会变成定时扰民的
   * 喇叭，而且扰的是隔壁床的人。
   */
  const armNoAnswerTimer = useCallback(() => {
    if (noAnswerTimerRef.current) clearTimeout(noAnswerTimerRef.current);
    noAnswerTimerRef.current = setTimeout(() => {
      noAnswerTimerRef.current = null;
      if (proactiveAnsweredRef.current) return;
      // 没人应答：停掉录音，安静收场，不再呼叫
      stopASR();
      clearSilenceTimer();
      setMessages([]);
      reportProactiveOutcome(false);
    }, PROACTIVE_NO_ANSWER_MS);
  }, [stopASR, clearSilenceTimer, reportProactiveOutcome]);

  // 卸载时清掉无人应答收场计时器
  useEffect(() => () => {
    if (noAnswerTimerRef.current) clearTimeout(noAnswerTimerRef.current);
  }, []);

  // 让 useTTS 的 onPlaybackDone 始终指向最新的 finishEndSession
  useEffect(() => {
    onPlaybackDoneRef.current = () => {
      finishEndSession();
      // 普通一轮播完（不在结束流程里）：重新开始等他说话
      if (!isEndingRef.current) armSilenceTimer();
    };
  }, [finishEndSession, armSilenceTimer]);

  const doEndSession = useCallback(async () => {
    clearSilenceTimer();
    const sessionId = sessionIdRef.current;
    stopASR();                 // 先停止收音，但不停 TTS——告别还要靠它说出来
    setShowEndDialog(false);
    isEndingRef.current = true;
    closingTextDoneRef.current = false;

    // 兜底：万一告别一句都没播出来（网络断了、TTS 挂了），
    // onPlaybackDone 永远不会触发，界面会卡在那儿回不去
    endFallbackTimerRef.current = setTimeout(() => {
      closingTextDoneRef.current = true;
      ttsPlayingRef.current = false;
      finishEndSession();
    }, 45000);

    try {
      await fetchClosing(sessionId);
    } catch (err) {
      console.warn('[HomeScreen] 收束告别失败:', err);
    }

    // fetchClosing 返回只代表**文字**流完了，语音通常还在后台排队播。
    // 标记文字已完成后再试一次：如果语音也已经播空了（短告别常见），
    // 这次调用就会真正收尾；否则等 onPlaybackDone 来收。
    closingTextDoneRef.current = true;
    finishEndSession();
  }, [fetchClosing, stopASR, finishEndSession, ttsPlayingRef]);

  // 危机时用暖琥珀色压过情绪光晕：这块屏幕是给正处在危机里的老人看的，
  // 要的是安全感，不是警报感
  const auraColors = isCrisis
    ? Design.colors.aura.crisis
    : Design.colors.aura[currentEmotion as keyof typeof Design.colors.aura] ||
      Design.colors.aura.neutral;

  // 抽象可视化的四态：speaking > thinking > listening > idle（TTS 播放时
  // ASR 只是被静音，status 仍可能是 'listening'，说话态必须压过听态）
  const orbPhase = derivePhase({
    isPlaying: ttsIsPlaying,
    isLLMStreaming,
    asrStatus: status,
  });

  const callCaregiver = useCallback(async () => {
    try {
      await fetch(
        `http://localhost:8050/llm/crisis/escalate?session_id=${encodeURIComponent(sessionIdRef.current)}`,
        { method: 'POST' },
      );
      setErrorMessage('已经通知护理员了，他们马上过来。');
    } catch {
      setErrorMessage('没能联系上护理员，请直接按房间里的呼叫铃。');
    }
  }, []);

  // 构建包含 typing 指示器的消息列表
  const displayMessages = isLLMStreaming && streamingIndexRef.current === null
    ? [...messages, { role: 'assistant' as const, text: '', isInterim: true }]
    : messages;

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: auraColors[0] }]}>
      <View style={styles.headerRow}>
        <StatusBar status={status} />
        <TouchableOpacity
          style={styles.viewModeToggle}
          onPress={toggleViewMode}
          accessibilityRole="button"
          accessibilityLabel={viewMode === 'orb' ? '切换到对话文字' : '切换到抽象圆点'}
        >
          <Text style={styles.viewModeToggleText}>
            {viewMode === 'orb' ? '看文字' : '看圆'}
          </Text>
        </TouchableOpacity>
      </View>

      {viewMode === 'chat' ? (
        <>
          <View style={styles.transcriptWrapper}>
            <TranscriptArea messages={displayMessages} currentEmotion={currentEmotion} />
          </View>

          <View style={styles.visualizerContainer}>
            <Waveform isActive={status === 'listening'} analyser={analyser} />
          </View>
        </>
      ) : (
        <View style={styles.orbWrapper}>
          <OrbVisualizer phase={orbPhase} analyser={analyser} auraColors={auraColors} />
        </View>
      )}

      {isCrisis && (
        <TouchableOpacity
          style={styles.caregiverButton}
          onPress={callCaregiver}
          accessibilityRole="button"
          accessibilityLabel="联系护理员"
        >
          <Text style={styles.caregiverButtonText}>联系护理员</Text>
        </TouchableOpacity>
      )}

      <ActionButton isRecording={isRecording} onPress={toggleConversation} />

      <ErrorToast
        message={errorMessage}
        visible={errorMessage !== ''}
        onDismiss={() => setErrorMessage('')}
      />

      {/*
        危机时不硬性禁用结束（把人困在界面里同样有害），改为换一套挽留的说法，
        并把「叫护理员」放在更顺手的位置——目的是不让他一个人待着，不是不让他退出。
      */}
      <ConfirmDialog
        visible={showEndDialog}
        title={isCrisis ? '先别急着走' : '结束对话'}
        message={
          isCrisis
            ? '我有点担心你，不太想让你一个人待着。要不要我帮你把护理员叫过来？'
            : '今天和您聊天很开心，下次再见。要结束吗？'
        }
        confirmLabel={isCrisis ? '叫护理员' : '结束'}
        cancelLabel={isCrisis ? '再陪我聊会儿' : '继续聊天'}
        onConfirm={isCrisis ? () => { setShowEndDialog(false); callCaregiver(); } : doEndSession}
        onCancel={() => setShowEndDialog(false)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  headerRow: {
    position: 'relative',
  },
  viewModeToggle: {
    position: 'absolute',
    right: 16,
    top: 8,
    minWidth: 44,
    minHeight: 44,
    paddingHorizontal: 14,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: 20,
    backgroundColor: Design.colors.surface,
    borderWidth: 1,
    borderColor: Design.colors.outline,
  },
  viewModeToggleText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 14,
    fontWeight: '600',
    color: Design.colors.text.secondary,
  },
  transcriptWrapper: {
    flex: 1,
    minHeight: 0,
  },
  visualizerContainer: {
    height: 100,
    justifyContent: 'center',
    alignItems: 'center',
  },
  orbWrapper: {
    flex: 1,
    minHeight: 0,
  },
  caregiverButton: {
    alignSelf: 'center',
    paddingHorizontal: 32,
    paddingVertical: 14,
    borderRadius: Design.layout.radius,
    backgroundColor: Design.colors.crisis,
    marginBottom: 12,
  },
  caregiverButtonText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 20,
    fontWeight: '600',
    color: Design.colors.onPrimary,
  },
});
