import { useState, useCallback, useRef } from 'react';
import { fetch as expoFetch, type FetchRequestInit } from 'expo/fetch';
import { TTSParams } from '../constants/TTS';
import { getElderId } from '../constants/Session';
import { API_BASE_URL } from '../constants/Api';

interface UseLLMOptions {
  baseUrl?: string;
  onSentence?: (sentence: string, ttsParams: TTSParams, category: string) => void;
  onDelta?: (deltaText: string) => void;
  onDone?: (strategyName?: string) => void;
}

/**
 * 送去合成的最小片段长度。
 *
 * 逐句流水线是为了压掉「等整段生成完才出声」的那几秒静默，但如果每凑够一句就
 * 发一次 TTS，CARE 框架的 C 步骤（「哦，是啊。」这种 ≤10 字的短句）会单独变成
 * 一次合成请求——既多一次往返，语流也会被切碎。
 *
 * 所以这里攒到 12 个字才发：第一次出声仍然远早于整段生成结束，同时把过短的
 * C 步骤和紧随其后的 A 步骤并成一次合成，语气更连贯。
 */
const MIN_TTS_CHUNK_CHARS = 12;

/** 从缓冲区里切出所有「完整句子」，返回句子拼成的串和剩余不完整的尾巴。 */
const takeCompleteSentences = (buffer: string): { ready: string; rest: string } => {
  const re = /[^。！？.!?\n]*[。！？.!?\n]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(buffer)) !== null) {
    lastIndex = re.lastIndex;
  }
  return { ready: buffer.slice(0, lastIndex), rest: buffer.slice(lastIndex) };
};

export const useLLM = (options: UseLLMOptions = {}) => {
  const {
    baseUrl = API_BASE_URL,
    onSentence,
    onDelta,
    onDone,
  } = options;

  // elder_id 跨会话稳定，读一次即可。getElderId() 现在是异步的（原生端走
  // AsyncStorage），用惰性 ref 缓存这个 Promise 本身，而不是缓存 resolve 后的
  // 值——这样不管调用方多早发起第一个请求，都能等到同一次读取结果，不会在
  // AsyncStorage 还没返回时就把空值/默认值发出去。
  const elderIdPromiseRef = useRef<Promise<string> | null>(null);
  if (elderIdPromiseRef.current === null) {
    elderIdPromiseRef.current = getElderId();
  }
  // 当前这条流的中止句柄。老人在回复生成到一半又开口时，这条回复要就地作废，
  // 否则会出现两条回复（第二条常常还跟第一条重复）。
  const abortRef = useRef<AbortController | null>(null);

  const [response, setResponse] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [strategyName, setStrategyName] = useState('');
  const [isCrisis, setIsCrisis] = useState(false);

  /**
   * 消费一条 SSE 流。/llm/stream 和 /llm/closing 的事件结构完全一致
   * （meta → delta... → done），所以两者共用这一段。
   */
  const runStream = useCallback(async (
    url: string,
    // expo/fetch 自己的 init 类型，不是 DOM 的 RequestInit——后者的 body 允许 null，
    // expo/fetch 不接受。三个调用点只传 method/headers/body，都在这个类型范围内。
    init?: FetchRequestInit,
    fallbackText = '哎呀，我刚才走神了，没听清您说什么。能麻烦您再说一遍吗？',
  ) => {
    setResponse('');
    setIsStreaming(true);
    let fullText = '';
    let ttsParams: TTSParams = { speed: 1.0, pitch: 0, style: 'neutral' };
    let category = 'neutral';
    let capturedStrategyName = '';
    setStrategyName('');
    setIsCrisis(false);

    // 逐句流水线的缓冲：pending 攒的是已经成句、但还没够长到值得发一次合成的文本
    let pending = '';
    let blocked = false;
    let blockReason = '';
    const emitChunk = (chunk: string) => {
      const trimmed = chunk.trim();
      if (trimmed) onSentence?.(trimmed, ttsParams, category);
    };

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      // expo/fetch 而非全局 fetch：RN 的全局 fetch 基于 XMLHttpRequest，不实现流式
      // 响应体，res.body 拿不到，下面的 getReader() 必然失败。expo/fetch 提供真正的
      // ReadableStream，且同样支持 AbortController（打断逻辑依赖 signal）。
      const res = await expoFetch(url, { ...init, signal: controller.signal });

      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) {
        throw new Error('ReadableStream not supported in this environment');
      }

      const decoder = new TextDecoder();
      let sseBuffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        sseBuffer += decoder.decode(value, { stream: true });

        const parts = sseBuffer.split('\n\n');
        sseBuffer = parts.pop() || '';

        for (const part of parts) {
          if (part.startsWith('data: ')) {
            try {
              const data = JSON.parse(part.slice(6));
              if (data.type === 'meta') {
                // 后端在调用生成模型之前先发的元信息：拿到 tts_params/category 后，
                // 下面的 delta 就能边生成边合成，不用等 done
                if (data.tts_params) {
                  ttsParams = data.tts_params;
                }
                category = data.category || 'neutral';
                capturedStrategyName = data.strategy_name || '';
                setStrategyName(capturedStrategyName);
                if (data.crisis) setIsCrisis(true);
              } else if (data.type === 'delta') {
                const deltaText = data.text;
                setResponse((prev) => prev + deltaText);
                fullText += deltaText;
                onDelta?.(deltaText);

                // 攒够一句、且累计长度达标就立刻送去合成
                pending += deltaText;
                const { ready, rest } = takeCompleteSentences(pending);
                if (ready && ready.trim().length >= MIN_TTS_CHUNK_CHARS) {
                  emitChunk(ready);
                  pending = rest;
                }
              } else if (data.type === 'done') {
                // meta 已经给过这些字段；done 再给一次是为了兼容，以两者一致为准
                if (data.tts_params) {
                  ttsParams = data.tts_params;
                }
                category = data.category || category;
                capturedStrategyName = data.strategy_name || capturedStrategyName;
                setStrategyName(capturedStrategyName);
                if (data.crisis) setIsCrisis(true);
              } else if (data.type === 'blocked') {
                // 服务端护栏拒绝了这次主动开口（夜间静默/每日上限/连续无应答/
                // 危机警戒）。安静收场——不重试，也不要提示老人。
                blocked = true;
                blockReason = data.reason || 'unknown';
                console.log('[useLLM] 主动开口被护栏拦下:', blockReason);
              } else if (data.type === 'error') {
                console.error('LLM Service Error:', data.message);
                const errText = `\n[系统错误: ${data.message}]`;
                setResponse((prev) => prev + errText);
                onDelta?.(errText);
              }
            } catch (e) {
              console.warn('Failed to parse SSE chunk:', part);
            }
          }
        }
      }

      if (blocked) {
        setIsStreaming(false);
        return { blocked: true, reason: blockReason, fullText: '' };
      }

      // 收尾：把还没达到最小长度的尾巴补发出去（回复很短时，这里才是唯一一次合成）
      if (pending.trim()) {
        emitChunk(pending);
        pending = '';
      }

      // 流完成回调（传递策略名称给前端气泡标签）
      onDone?.(capturedStrategyName);
      return { blocked: false, reason: '', fullText };
    } catch (err) {
      // 主动作废（老人又开口了）不是错误，别弹"我走神了"那句
      if (controller.signal.aborted) {
        console.log('[useLLM] 回复已作废（老人继续说话）');
        return { blocked: false, reason: 'aborted', fullText: '' };
      }
      console.error('LLM Fetch Error:', err);
      // fallbackText 为空串表示"这条链路失败时不许说话"（主动开口就是这样：
      // 老人根本没开口，冒出一句"我刚才走神了"是荒谬的）
      if (fallbackText) {
        setResponse(fallbackText);
        onDelta?.(fallbackText);
      }
      onDone?.();
      return { blocked: false, reason: 'error', fullText: '' };
    } finally {
      setIsStreaming(false);
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [onSentence, onDelta, onDone]);

  /** 作废当前这条回复（老人在 AI 说话时又开口了）。 */
  const abort = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  /** 普通一轮对话。 */
  const fetchReply = useCallback(
    async (text: string, emotion: any, sessionId: string) => {
      const elderId = await elderIdPromiseRef.current!;
      return runStream(`${baseUrl}/llm/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          emotion: emotion || { label: 'neutral' },
          session_id: sessionId,
          elder_id: elderId,
        }),
      });
    },
    [baseUrl, runStream],
  );

  /**
   * 结束对话前的收束告别（回顾今天聊到的 → 肯定 → 道别 → 约定下次）。
   * 必须在 reset() 之前调用——reset 会清掉后端本次会话的滚动摘要，
   * 而这段回顾正是靠那份摘要生成的。
   */
  const fetchClosing = useCallback(
    async (sessionId: string) => {
      const elderId = await elderIdPromiseRef.current!;
      return runStream(
        `${baseUrl}/llm/closing?session_id=${encodeURIComponent(sessionId)}` +
          `&elder_id=${encodeURIComponent(elderId)}`,
        { method: 'POST' },
        '今天跟你聊得挺好的。你早点歇着，明儿这个点我还在这儿。',
      );
    },
    [baseUrl, runStream],
  );

  /**
   * AI 主动开口。trigger:
   *   'scheduled' —— 到点了主动招呼（当前无进行中的会话）
   *   'silence'   —— 对话中老人静默了一会儿，AI 先接上话
   *
   * 护栏在服务端。返回 blocked=true 时安静收场，**不要重试、不要提示老人**。
   * 生成失败时也不说兜底文案——老人根本没开口，冒出一句「我刚才走神了」
   * 是荒谬的（所以 fallbackText 传空串）。
   */
  const fetchProactive = useCallback(
    async (sessionId: string, trigger: 'scheduled' | 'silence') => {
      const elderId = await elderIdPromiseRef.current!;
      return runStream(
        `${baseUrl}/llm/proactive?session_id=${encodeURIComponent(sessionId)}` +
          `&elder_id=${encodeURIComponent(elderId)}` +
          `&trigger=${trigger}`,
        { method: 'POST' },
        '',
      );
    },
    [baseUrl, runStream],
  );

  /**
   * 主动招呼之后老人到底有没有搭话。连续无应答达到阈值后，服务端当天不再
   * 主动开口——没有这条，设备会变成定时扰民的喇叭。
   */
  const reportProactiveOutcome = useCallback(async (answered: boolean) => {
    try {
      const elderId = await elderIdPromiseRef.current!;
      await fetch(
        `${baseUrl}/llm/proactive/outcome?elder_id=${encodeURIComponent(elderId)}` +
          `&answered=${answered}`,
        { method: 'POST' },
      );
    } catch (err) {
      console.warn('[useLLM] 上报主动开口结果失败:', err);
    }
  }, [baseUrl]);

  /**
   * 重置本地流式状态；传入 sessionId 时，同时通知后端释放该会话的服务端状态
   * （对话历史 / 策略延续 / 类别延续）。
   *
   * 之前这里只清前端状态、从不通知后端。现在每次对话用全新的 session_id，
   * 新会话本身就是干净的；真正需要后端 reset 的是**对话结束时**——否则
   * 后端 self.sessions 会随着一次次对话不断堆积用不到的旧会话状态。
   */
  const reset = useCallback(async (sessionId?: string) => {
    setResponse('');
    setIsStreaming(false);
    setStrategyName('');
    setIsCrisis(false);
    if (!sessionId) return;
    try {
      // 带上 elder_id：后端据此把这次对话的摘要留档进长程台账，
      // 下次才能回指「上次咱们聊到…」
      const elderId = await elderIdPromiseRef.current!;
      await fetch(
        `${baseUrl}/llm/reset?session_id=${encodeURIComponent(sessionId)}` +
          `&elder_id=${encodeURIComponent(elderId)}`,
        { method: 'POST' },
      );
    } catch (err) {
      console.warn('[useLLM] 重置后端会话失败:', err);
    }
  }, [baseUrl]);

  return {
    response, fetchReply, fetchClosing, fetchProactive, reportProactiveOutcome,
    abort, isStreaming, reset, strategyName, isCrisis,
  };
};
