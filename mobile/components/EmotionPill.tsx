import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Design } from '../constants/Design';

interface EmotionPillProps {
  label: string;
  type: 'emotion' | 'category';
}

export const EmotionPill: React.FC<EmotionPillProps> = ({ label, type }) => {
  const isEmotion = type === 'emotion';

  return (
    <View style={[styles.pill, isEmotion ? styles.emotionPill : styles.categoryPill]}>
      <Text style={[styles.label, isEmotion ? styles.emotionLabel : styles.categoryLabel]}>
        {isEmotion ? `感受：${label}` : `状态：${label}`}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  pill: {
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: Design.layout.radiusSmall,
    alignSelf: 'flex-start',
  },
  emotionPill: {
    backgroundColor: 'rgba(193, 123, 106, 0.15)',
  },
  categoryPill: {
    backgroundColor: 'rgba(193, 123, 106, 0.08)',
    borderWidth: 0.5,
    borderColor: 'rgba(193, 123, 106, 0.20)',
  },
  label: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.caption.fontSize,
    lineHeight: Design.typography.caption.lineHeight,
  },
  emotionLabel: {
    color: Design.colors.onPrimaryContainer,
    fontWeight: '600',
  },
  categoryLabel: {
    color: Design.colors.secondary,
    fontWeight: '500',
  },
});
