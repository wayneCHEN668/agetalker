import React, { useEffect, useRef } from 'react';
import { ScrollView, Text, StyleSheet, View } from 'react-native';
import { Design } from '../constants/Design';

interface TranscriptAreaProps {
  history: { text: string; emotion?: any; category_zh?: string }[];
  interim?: string;
}

export const TranscriptArea: React.FC<TranscriptAreaProps> = ({ history, interim }) => {
  const scrollViewRef = useRef<ScrollView>(null);

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    setTimeout(() => {
      scrollViewRef.current?.scrollToEnd({ animated: true });
    }, 100);
  }, [history, interim]);

  return (
    <View style={styles.outerContainer}>
      <ScrollView 
        ref={scrollViewRef}
        style={styles.container} 
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        {history.length === 0 && !interim && (
          <Text style={styles.placeholder}>您可以随时对我说话，我会一直在这里陪着您。</Text>
        )}
        
        {history.map((item, index) => (
          <View key={`history-${index}`} style={styles.bubble}>
            <Text style={styles.text}>
              {item.text}
            </Text>
            <View style={styles.tagRow}>
              {item.emotion?.label_zh && (
                <View style={styles.emotionTag}>
                  <Text style={styles.emotionText}>感受：{item.emotion.label_zh}</Text>
                </View>
              )}
              {item.category_zh && (
                <View style={styles.categoryTag}>
                  <Text style={styles.categoryText}>状态：{item.category_zh}</Text>
                </View>
              )}
            </View>
          </View>
        ))}
        
        {interim ? (
          <View style={[styles.bubble, styles.interimBubble]}>
            <Text style={[styles.text, styles.interimText]}>{interim}</Text>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  outerContainer: {
    flex: 1,
    maxHeight: 350,
    marginHorizontal: Design.layout.spacing,
    marginTop: 10,
  },
  container: {
    flex: 1,
  },
  content: {
    paddingVertical: 10,
    gap: 20,
  },
  bubble: {
    backgroundColor: Design.colors.primaryContainer,
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderRadius: Design.layout.radius,
    borderBottomLeftRadius: 4,
    alignSelf: 'flex-start',
    maxWidth: '90%',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 10,
    elevation: 2,
  },
  interimBubble: {
    backgroundColor: Design.colors.surface,
    borderStyle: 'dashed',
    borderWidth: 1.5,
    borderColor: Design.colors.primary,
    opacity: 0.7,
  },
  text: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.message.fontSize,
    lineHeight: Design.typography.message.lineHeight,
    color: Design.colors.onPrimaryContainer,
  },
  interimText: {
    color: Design.colors.text.secondary,
  },
  tagRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    marginTop: 8,
    gap: 8,
  },
  emotionTag: {
    backgroundColor: 'rgba(74, 103, 65, 0.1)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
  },
  emotionText: {
    fontSize: 14,
    color: Design.colors.primary,
    fontWeight: '600',
  },
  categoryTag: {
    backgroundColor: 'rgba(74, 103, 65, 0.06)',
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 0.5,
    borderColor: 'rgba(74, 103, 65, 0.18)',
  },
  categoryText: {
    fontSize: 13,
    color: Design.colors.secondary,
    fontWeight: '500',
  },
  placeholder: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 18,
    lineHeight: 28,
    color: Design.colors.text.hint,
    textAlign: 'center',
    marginTop: 60,
    paddingHorizontal: 40,
  },
});
