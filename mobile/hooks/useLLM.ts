import { useState, useCallback } from 'react';

export const useLLM = (baseUrl = 'http://localhost:8050') => {
  const [response, setResponse] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);

  const fetchReply = useCallback(async (text: string, emotion: any) => {
    setResponse('');
    setIsStreaming(true);

    try {
      // Note: Standard fetch streaming works in Browser context.
      // For Native (iOS/Android), you might need react-native-sse or similar.
      const res = await fetch(`${baseUrl}/llm/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          text, 
          emotion, 
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
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        
        // Split by SSE message separator
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || ''; // Keep the last partial message in buffer

        for (const part of parts) {
          if (part.startsWith('data: ')) {
            try {
              const data = JSON.parse(part.slice(6));
              if (data.type === 'delta') {
                setResponse(prev => prev + data.text);
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
    } catch (err) {
      console.error('LLM Fetch Error:', err);
      setResponse('哎呀，我刚才走神了，没听清您说什么。能麻烦您再说一遍吗？');
    } finally {
      setIsStreaming(false);
    }
  }, [baseUrl]);

  const reset = useCallback(() => {
    setResponse('');
    setIsStreaming(false);
  }, []);

  return { response, fetchReply, isStreaming, reset };
};
