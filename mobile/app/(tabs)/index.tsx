import React, { useState, useCallback } from 'react';
import { StyleSheet, View, SafeAreaView } from 'react-native';
import { Design } from '@/constants/Design';
import { CATEGORY_ZH_MAP } from '@/constants/Category';
import { StatusBar } from '@/components/StatusBar';
import { TranscriptArea } from '@/components/TranscriptArea';
import { Waveform } from '@/components/Waveform';
import { ResponseArea } from '@/components/ResponseArea';
import { ActionButton } from '@/components/ActionButton';

import { useASR } from '@/hooks/useASR';
import { useLLM } from '@/hooks/useLLM';
import { useTTS } from '@/hooks/useTTS';

export default function HomeScreen() {
  const [history, setHistory] = useState<
    {text: string; emotion?: any; category_zh?: string}[]
  >([]);
  const [interim, setInterim] = useState('');
  const [currentEmotion, setCurrentEmotion] = useState('neutral');
  
  // 1. Initialize TTS
  const { speak, stop: stopTTS } = useTTS();

  // 2. Initialize LLM with onSentence callback for parallel TTS
  // ttsParams and category come from the backend LLM done event (semantic-driven)
  const { response, fetchReply, reset: resetLLM, strategyName } = useLLM({
    onSentence: (sentence, ttsParams, category) => {
      console.log('[HomeScreen] Triggering TTS for sentence:', sentence, category);
      speak(sentence, ttsParams, category);

      // Surface the psychological category in the last transcript bubble.
      // The conversation is strictly sequential — the last history item is always
      // the user utterance that triggered this LLM call.
      const zh = CATEGORY_ZH_MAP[category] || category;
      setHistory(prev => {
        if (prev.length === 0) return prev;
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          category_zh: zh,
        };
        return updated;
      });
    }
  });

  // 3. Initialize ASR with echo cancellation (events handled internally in hook)
  const { start, stop: stopASR, status, isRecording, analyser } = useASR({
    onTranscript: (text, isFinal, emotion) => {
      if (isFinal) {
        setHistory(prev => [...prev, { text, emotion }]);
        setInterim('');
        
        const emotionLabel = emotion?.label || 'neutral';
        setCurrentEmotion(emotionLabel);
        
        // STEP 4: Call LLM with parallel sentence processing
        // Now passing the full emotion object instead of just the label string
        fetchReply(text, emotion);
      } else {
        setInterim(text);
      }
    },
  });

  const toggleConversation = () => {
    if (isRecording) {
      stopASR();
      stopTTS();
    } else {
      setHistory([]);
      setInterim('');
      setCurrentEmotion('neutral');
      resetLLM();
      stopTTS(); // Ensure any residual audio is killed
      start();
    }
  };

  // Get Aura colors based on current emotion
  const auraColors = Design.colors.aura[currentEmotion as keyof typeof Design.colors.aura] || Design.colors.aura.neutral;

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: auraColors[0] }]}>
      <StatusBar status={status} />
      
      <View style={styles.content}>
        <TranscriptArea history={history} interim={interim} />
        
        <View style={styles.visualizerContainer}>
          <Waveform 
            isActive={status === 'listening'} 
            analyser={analyser}
          />
        </View>
        
        <ResponseArea response={response} strategyName={strategyName} />
      </View>
      
      <ActionButton 
        isRecording={isRecording} 
        onPress={toggleConversation} 
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    flex: 1,
    justifyContent: 'space-between',
    paddingTop: 20,
  },
  visualizerContainer: {
    height: 120,
    justifyContent: 'center',
    alignItems: 'center',
  }
});
