import React, { useEffect, useRef } from 'react';
import { ScrollView, Text, StyleSheet, View } from 'react-native';
import { Design } from '../constants/Design';
import { ChatBubble, ChatMessage } from './ChatBubble';

interface TranscriptAreaProps {
  messages: ChatMessage[];
  currentEmotion?: string;
}

export const TranscriptArea: React.FC<TranscriptAreaProps> = ({ messages, currentEmotion }) => {
  const scrollViewRef = useRef<ScrollView>(null);

  useEffect(() => {
    setTimeout(() => {
      scrollViewRef.current?.scrollToEnd({ animated: true });
    }, 100);
  }, [messages]);

  return (
    <View style={styles.container}>
      <ScrollView
        ref={scrollViewRef}
        style={styles.scroll}
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={true}
      >
        {messages.length === 0 && (
          <Text style={styles.placeholder}>
            您可以随时对我说话，{'\n'}我会一直在这里陪着您。
          </Text>
        )}

        {messages.map((msg, index) => (
          <ChatBubble key={`msg-${index}`} message={msg} currentEmotion={currentEmotion} />
        ))}

        {/* 底部留白，确保最后一条消息不被按钮遮挡 */}
        <View style={styles.bottomSpacer} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    marginHorizontal: Design.layout.spacing,
  },
  scroll: {
    flex: 1,
  },
  content: {
    paddingVertical: 12,
  },
  placeholder: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 18,
    lineHeight: 30,
    color: Design.colors.text.hint,
    textAlign: 'center',
    marginTop: 40,
    paddingHorizontal: 40,
  },
  bottomSpacer: {
    height: 20,
  },
});
