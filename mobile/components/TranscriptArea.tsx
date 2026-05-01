import React, { useEffect, useRef } from 'react';
import { ScrollView, Text, StyleSheet, View } from 'react-native';
import { Design } from '../constants/Design';

interface TranscriptAreaProps {
  history: { text: string, emotion?: any }[];
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
        showsVerticalScrollIndicator={true}
      >
        {history.length === 0 && !interim && (
          <Text style={styles.placeholder}>等待您的发言...</Text>
        )}
        
        {history.map((item, index) => (
          <View key={`history-${index}`} style={styles.bubble}>
            <Text style={styles.text}>
              {item.text}
              {item.emotion?.label_zh && (
                <Text style={styles.emotionText}> [{item.emotion.label_zh}]</Text>
              )}
            </Text>
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
    maxHeight: 400, // Limit height to make it scrollable
    marginHorizontal: Design.layout.spacing,
    marginTop: 10,
  },
  container: {
    flex: 1,
  },
  content: {
    paddingVertical: 10,
    gap: 12,
  },
  bubble: {
    backgroundColor: Design.colors.surfaceContainerLow,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 20,
    borderTopLeftRadius: 4, // Chat-like style
    alignSelf: 'flex-start',
    maxWidth: '85%',
    // Subtle shadow for premium feel
    boxShadow: '0px 1px 2px rgba(0, 0, 0, 0.05)',
    elevation: 2,
  },
  interimBubble: {
    backgroundColor: Design.colors.surfaceContainerLowest,
    borderStyle: 'dashed',
    borderWidth: 1,
    borderColor: Design.colors.outlineVariant,
    opacity: 0.8,
  },
  text: {
    fontFamily: Design.typography.fontFamily,
    ...Design.typography.bodyLarge,
    color: Design.colors.onSurface,
    lineHeight: 28,
  },
  interimText: {
    color: Design.colors.onSurfaceVariant,
  },
  emotionText: {
    fontSize: 14,
    color: Design.colors.primary,
    fontWeight: '600',
    fontStyle: 'italic',
  },
  placeholder: {
    fontFamily: Design.typography.fontFamily,
    ...Design.typography.bodyLarge,
    color: Design.colors.outline,
    textAlign: 'center',
    marginTop: 40,
  },
});
