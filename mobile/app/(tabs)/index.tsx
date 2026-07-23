import React, { useState, useCallback, useRef } from 'react';
import { StyleSheet, View, SafeAreaView } from 'react-native';
import { Design } from '@/constants/Design';
import { CATEGORY_ZH_MAP } from '@/constants/Category';
import { StatusBar } from '@/components/StatusBar';
import { TranscriptArea } from '@/components/TranscriptArea';
import { Waveform } from '@/components/Waveform';
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

  // 跟踪流式 AI 消息在 messages 中的索引
  const streamingIndexRef = useRef<number | null>(null);

  // 1. TTS
  const { speak, stop: stopTTS } = useTTS();

  // 2. LLM
  const { fetchReply, reset: resetLLM } = useLLM({
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
    },
  });

  // 3. ASR
  const { start, stop: stopASR, status, isRecording, analyser } = useASR({
    onTranscript: (text, isFinal, emotion) => {
      if (isFinal) {
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
        fetchReply(text, emotion);
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
  });

  const toggleConversation = useCallback(() => {
    if (isRecording) {
      // 停止录音 — 先确认
      if (messages.length > 0) {
        setShowEndDialog(true);
      } else {
        doEndSession();
      }
    } else {
      setMessages([]);
      setCurrentEmotion('neutral');
      streamingIndexRef.current = null;
      setIsLLMStreaming(false);
      setErrorMessage('');
      resetLLM();
      stopTTS();
      start();
    }
  }, [isRecording, messages.length]);

  const doEndSession = useCallback(() => {
    stopASR();
    stopTTS();
    setShowEndDialog(false);
    // 短暂显示告别状态后清除
    setTimeout(() => {
      setMessages([]);
      setCurrentEmotion('neutral');
      streamingIndexRef.current = null;
      setIsLLMStreaming(false);
      resetLLM();
    }, 2500);
  }, []);

  const auraColors =
    Design.colors.aura[currentEmotion as keyof typeof Design.colors.aura] ||
    Design.colors.aura.neutral;

  // 构建包含 typing 指示器的消息列表
  const displayMessages = isLLMStreaming && streamingIndexRef.current === null
    ? [...messages, { role: 'assistant' as const, text: '', isInterim: true }]
    : messages;

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: auraColors[0] }]}>
      <StatusBar status={status} />

      <View style={styles.transcriptWrapper}>
        <TranscriptArea messages={displayMessages} currentEmotion={currentEmotion} />
      </View>

      <View style={styles.visualizerContainer}>
        <Waveform isActive={status === 'listening'} analyser={analyser} />
      </View>

      <ActionButton isRecording={isRecording} onPress={toggleConversation} />

      <ErrorToast
        message={errorMessage}
        visible={errorMessage !== ''}
        onDismiss={() => setErrorMessage('')}
      />

      <ConfirmDialog
        visible={showEndDialog}
        title="结束对话"
        message="今天和您聊天很开心，下次再见。要结束吗？"
        confirmLabel="结束"
        cancelLabel="继续聊天"
        onConfirm={doEndSession}
        onCancel={() => setShowEndDialog(false)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
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
});
