import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated } from 'react-native';
import { Design } from '../constants/Design';
import { EmotionPill } from './EmotionPill';

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  emotion?: { label?: string; label_zh?: string };
  category_zh?: string;
  strategyName?: string;
  isInterim?: boolean;
  /** 这条回复说到一半被老人插话打断了 */
  interrupted?: boolean;
}

const TypingIndicator: React.FC = () => {
  const dots = [
    useRef(new Animated.Value(0.3)).current,
    useRef(new Animated.Value(0.3)).current,
    useRef(new Animated.Value(0.3)).current,
  ];

  useEffect(() => {
    const loops = dots.map((dot, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(i * 150),
          Animated.timing(dot, { toValue: 1, duration: 350, useNativeDriver: true }),
          Animated.timing(dot, { toValue: 0.3, duration: 350, useNativeDriver: true }),
        ]),
      ),
    );
    loops.forEach((l) => l.start());
    return () => loops.forEach((l) => l.stop());
  }, []);

  return (
    <View style={typingStyles.row}>
      {dots.map((dot, i) => (
        <Animated.View key={i} style={[typingStyles.dot, { opacity: dot }]} />
      ))}
    </View>
  );
};

const typingStyles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingVertical: 4,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: Design.colors.primary,
  },
});

// 情绪 → 头像底色映射（暖暮调，subtle tints）
const EMOTION_AVATAR_COLORS: Record<string, string> = {
  neutral:   '#C17B6A',
  happy:     '#D4956E',
  sad:       '#9E8B9A',
  angry:     '#C47A6E',
  fearful:   '#A4899E',
  disgusted: '#A89A7E',
  surprised: '#B8957A',
};

interface ChatBubbleProps {
  message: ChatMessage;
  currentEmotion?: string;
}

export const ChatBubble: React.FC<ChatBubbleProps> = ({ message, currentEmotion }) => {
  const isUser = message.role === 'user';
  const isInterim = message.isInterim;

  const bubbleStyle = [
    styles.bubble,
    isUser ? styles.userBubble : styles.assistantBubble,
    isInterim && styles.interimBubble,
  ];

  const textStyle = [
    styles.text,
    isUser ? styles.userText : styles.assistantText,
    isInterim && styles.interimText,
  ];

  return (
    <View style={[styles.row, isUser ? styles.rowRight : styles.rowLeft]}>
      {/* AI 头像标识 */}
      {!isUser && (
        <View style={[
          styles.avatar,
          { backgroundColor: EMOTION_AVATAR_COLORS[currentEmotion || 'neutral'] || EMOTION_AVATAR_COLORS.neutral },
        ]}>
          <Text style={styles.avatarText}>伴</Text>
        </View>
      )}

      <View style={[styles.bubbleWrapper, isUser ? styles.userWrapper : styles.assistantWrapper]}>
        {/* 对话气泡 */}
        <View style={bubbleStyle}>
          {!isUser && message.strategyName ? (
            <Text style={styles.strategyBadge}>{message.strategyName}</Text>
          ) : null}
          {isInterim && !isUser && !message.text ? (
            <TypingIndicator />
          ) : (
            <Text style={textStyle}>{message.text}</Text>
          )}
        </View>

        {/* 标签放在气泡下方，同一行显示 */}
        {!isInterim && (message.emotion?.label_zh || message.category_zh) && (
          <View style={styles.tagRow}>
            {message.emotion?.label_zh && (
              <EmotionPill label={message.emotion.label_zh} type="emotion" />
            )}
            {message.category_zh && (
              <EmotionPill label={message.category_zh} type="category" />
            )}
          </View>
        )}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    marginBottom: 12,
  },
  rowRight: {
    justifyContent: 'flex-end',
  },
  rowLeft: {
    justifyContent: 'flex-start',
  },

  // 头像
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: Design.colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
    shadowColor: Design.colors.primary,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 3,
  },
  avatarText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 15,
    color: Design.colors.onPrimary,
    fontWeight: '600',
  },

  // 气泡外层（含标签）
  bubbleWrapper: {
    maxWidth: '82%',
  },
  userWrapper: {
    alignItems: 'flex-end',
  },
  assistantWrapper: {
    alignItems: 'flex-start',
  },

  // 气泡
  bubble: {
    paddingHorizontal: 18,
    paddingVertical: 14,
    borderRadius: Design.layout.radius,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.04,
    shadowRadius: 8,
    elevation: 2,
  },
  userBubble: {
    backgroundColor: Design.colors.primaryContainer,
    borderBottomRightRadius: 4,
  },
  assistantBubble: {
    backgroundColor: Design.colors.surface,
    borderBottomLeftRadius: 4,
    borderWidth: 1,
    borderColor: Design.colors.outline,
  },
  interimBubble: {
    borderStyle: 'dashed' as const,
    borderWidth: 1.5,
    borderColor: Design.colors.primary,
    backgroundColor: Design.colors.surfaceDim,
    opacity: 0.75,
  },

  // 文字
  text: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.message.fontSize,
    lineHeight: Design.typography.message.lineHeight,
  },
  userText: {
    color: Design.colors.onPrimaryContainer,
  },
  assistantText: {
    color: Design.colors.text.primary,
  },
  interimText: {
    color: Design.colors.text.secondary,
  },

  // 标签行（声音情绪 + 心理情绪同行）
  tagRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 4,
    alignSelf: 'flex-start',
  },
  strategyBadge: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 13,
    color: Design.colors.primary,
    fontWeight: '600',
    letterSpacing: 0.5,
    marginBottom: 6,
    // Chinese text — no textTransform needed
  },
});
