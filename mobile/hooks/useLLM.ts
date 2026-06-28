import { useState, useCallback } from 'react';
import { TTSParams } from '../constants/TTS';

interface UseLLMOptions {
  baseUrl?: string;
  onSentence?: (sentence: string, ttsParams: TTSParams, category: string) => void;
}

export const useLLM = (options: UseLLMOptions = {}) => {
  const { baseUrl = 'http://localhost:8050', onSentence } = options;
  const [response, setResponse] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [strategyName, setStrategyName] = useState('');

  const fetchReply = useCallback(async (text: string, emotion: any) => {
    setResponse('');
    setIsStreaming(true);
    let fullText = '';
    let ttsParams: TTSParams = { speed: 1.0, pitch: 0, style: 'neutral' };
    let category = 'neutral';
    setStrategyName('');

    try {
      const res = await fetch(`${baseUrl}/llm/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          emotion: emotion || { label: 'neutral' },
          session_id: 'default'
        }),
      });

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
              if (data.type === 'delta') {
                const deltaText = data.text;
                setResponse(prev => prev + deltaText);
                fullText += deltaText;
              } else if (data.type === 'done') {
                // Capture backend-computed TTS params, category, and strategy
                if (data.tts_params) {
                  ttsParams = data.tts_params;
                }
                category = data.category || 'neutral';
                setStrategyName(data.strategy_name || '');
              } else if (data.type === 'error') {
                console.error('LLM Service Error:', data.message);
                setResponse(prev => prev + `\n[系统错误: ${data.message}]`);
              }
            } catch (e) {
              console.warn('Failed to parse SSE chunk:', part);
            }
          }
        }
      }

      // Once full text is collected, trigger TTS with backend params
      if (fullText.trim()) {
        onSentence?.(fullText.trim(), ttsParams, category);
      }

    } catch (err) {
      console.error('LLM Fetch Error:', err);
      setResponse('哎呀，我刚才走神了，没听清您说什么。能麻烦您再说一遍吗？');
    } finally {
      setIsStreaming(false);
    }
  }, [baseUrl, onSentence]);

  const reset = useCallback(() => {
    setResponse('');
    setIsStreaming(false);
    setStrategyName('');
  }, []);

  return { response, fetchReply, isStreaming, reset, strategyName };
};
