import React, { useState } from 'react';
import { StyleSheet, View, SafeAreaView } from 'react-native';
import { Design } from '@/constants/Design';
import { StatusBar } from '@/components/StatusBar';
import { TranscriptArea } from '@/components/TranscriptArea';
import { Waveform } from '@/components/Waveform';
import { ResponseArea } from '@/components/ResponseArea';
import { ActionButton } from '@/components/ActionButton';

import { useASR } from '@/hooks/useASR';

export default function HomeScreen() {
  const [history, setHistory] = useState<string[]>([]);
  const [interim, setInterim] = useState('');
  const [response, setResponse] = useState('听起来今天有些疲惫，能告诉我是什么让您累了吗?');

  const { start, stop, status, isRecording, analyser } = useASR({
    onTranscript: (text, isFinal) => {
      if (isFinal) {
        setHistory(prev => [...prev, text]);
        setInterim('');
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
