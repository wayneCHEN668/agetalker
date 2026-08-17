import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import { Design } from '@/constants/Design';
import type { CardFace } from '@/constants/MemoryGame';

/** 点击区下限。通用无障碍标准是 44，这里翻倍——目标用户手抖。 */
export const CARD_MIN_SIZE = 64;

/** 小于这个尺寸就不显示中文词：挤成一团的字比没有字更难认。 */
export const CARD_WORD_MIN_SIZE = 92;

type Props = {
  face: CardFace;
  faceUp: boolean;
  matched: boolean;
  size: number;
  onPress: () => void;
};

export default function MemoryCard({ face, faceUp, matched, size, onPress }: Props) {
  const iconSize = Math.round(size * (size >= CARD_WORD_MIN_SIZE ? 0.4 : 0.52));
  const showWord = size >= CARD_WORD_MIN_SIZE;

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ disabled: matched }}
      accessibilityLabel={faceUp ? face.zh : '还没翻开的牌'}
      style={[
        styles.card,
        { width: size, height: size },
        faceUp ? (matched ? styles.matched : styles.faceUp) : styles.faceDown,
      ]}
    >
      {faceUp ? (
        <View style={styles.content}>
          <MaterialCommunityIcons
            name={face.icon}
            size={iconSize}
            color={Design.colors.onPrimaryContainer}
          />
          {showWord ? (
            <Text style={styles.word} numberOfLines={1}>
              {face.zh}
            </Text>
          ) : null}
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    minWidth: CARD_MIN_SIZE,
    minHeight: CARD_MIN_SIZE,
    borderRadius: Design.layout.radiusSmall,
    alignItems: 'center',
    justifyContent: 'center',
  },
  content: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  // 背面：素净的暖色块，不画花纹——花纹会被误认成图案
  faceDown: {
    backgroundColor: Design.colors.surfaceDim,
    borderWidth: 1,
    borderColor: Design.colors.outline,
  },
  faceUp: {
    backgroundColor: Design.colors.surface,
    borderWidth: 1,
    borderColor: Design.colors.outline,
  },
  // 配对成功：底色变暖，这是全局唯一的正向反馈。没有对应的负向反馈。
  matched: {
    backgroundColor: Design.colors.primaryContainer,
    borderWidth: 1,
    borderColor: Design.colors.primaryContainer,
  },
  word: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 14,
    color: Design.colors.text.secondary,
  },
});
