import React, { useState } from 'react';
import { StyleSheet, View, SafeAreaView } from 'react-native';
import { Design } from '@/constants/Design';
import { StatusBar } from '@/components/StatusBar';
import { TranscriptArea } from '@/components/TranscriptArea';
import { Waveform } from '@/components/Waveform';
import { ResponseArea } from '@/components/ResponseArea';
import { ActionButton } from '@/components/ActionButton';

import { useASR } from '@/hooks/useASR';
import { useLLM } from '@/hooks/useLLM';

export default function HomeScreen() {
  const [history, setHistory] = useState<{text: string, emotion?: any}[]>([]);
  const [interim, setInterim] = useState('');
  
  const { response, fetchReply, reset: resetLLM } = useLLM();

  const { start, stop, status, isRecording, analyser } = useASR({
    onTranscript: (text, isFinal, emotion) => {
      if (isFinal) {
        setHistory(prev => [...prev, { text, emotion }]);
        setInterim('');
        // STEP 3: Call LLM Service for psychological response
        fetchReply(text, emotion);
      } else {
        setInterim(text);
      }
    },
  });

  const toggleConversation = () => {
    if (isRecording) {
      stop();
    } else {
      setHistory([]);
      setInterim('');
      resetLLM();
      start();
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar status={status} />
      
      <View style={styles.content}>
        <TranscriptArea history={history} interim={interim} />
        
        <Waveform 
          isActive={status === 'listening'} 
          analyser={analyser}
        />
        
        <ResponseArea response={response} />
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
    backgroundColor: Design.colors.surface,
  },
  content: {
    flex: 1,
    justifyContent: 'space-between',
  },
});
