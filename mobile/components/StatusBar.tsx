import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated } from 'react-native';
import { Design } from '../constants/Design';

interface StatusBarProps {
  status: 'listening' | 'processing' | 'idle' | 'reconnecting';
}

const ThinkingDots: React.FC = () => {
  const dots = [
    useRef(new Animated.Value(0.3)).current,
    useRef(new Animated.Value(0.3)).current,
    useRef(new Animated.Value(0.3)).current,
  ];

  useEffect(() => {
    const loops = dots.map((dot, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(i * 200),
          Animated.timing(dot, {
            toValue: 1,
            duration: 400,
            useNativeDriver: true,
          }),
          Animated.timing(dot, {
            toValue: 0.3,
            duration: 400,
            useNativeDriver: true,
          }),
        ]),
      ),
    );
    loops.forEach((l) => l.start());
    return () => loops.forEach((l) => l.stop());
  }, []);

  return (
    <View style={styles.dotsRow}>
      {dots.map((dot, i) => (
        <Animated.View
          key={i}
          style={[styles.thinkingDot, { opacity: dot }]}
        />
      ))}
    </View>
  );
};

export const StatusBar: React.FC<StatusBarProps> = ({ status }) => {
  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (status === 'listening') {
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, {
            toValue: 1.05,
            duration: 800,
            useNativeDriver: true,
          }),
          Animated.timing(pulseAnim, {
            toValue: 1,
            duration: 800,
            useNativeDriver: true,
          }),
        ]),
      );
      loop.start();
      return () => loop.stop();
    } else {
      pulseAnim.setValue(1);
    }
  }, [status]);

  const isActive = status !== 'idle';

  const getStatusText = () => {
    switch (status) {
      case 'listening':    return '正在聆听';
      case 'processing':   return '思考中';
      // 不说「连接断开」这类技术词——对老人只说「稍等一下」，
      // 重连是后台自动完成的，他不需要做任何事
      case 'reconnecting': return '稍等一下';
      default:             return '准备聆听';
    }
  };

  const dotColor = status === 'listening'
    ? '#E8A838'
    : status === 'processing'
    ? Design.colors.primary
    : Design.colors.text.hint;

  return (
    <View style={styles.wrapper}>
      <Animated.View
        style={[
          styles.pill,
          isActive && styles.pillActive,
          { transform: [{ scale: pulseAnim }] },
        ]}
      >
        {status === 'processing' ? (
          <ThinkingDots />
        ) : (
          <View style={[styles.dot, { backgroundColor: dotColor }]} />
        )}
        <Text style={[styles.text, isActive && styles.textActive]}>
          {getStatusText()}
        </Text>
      </Animated.View>
    </View>
  );
};

const styles = StyleSheet.create({
  wrapper: {
    alignItems: 'center',
    paddingTop: 8,
    paddingBottom: 12,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: Design.colors.surfaceDim,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.04,
    shadowRadius: 4,
    elevation: 1,
  },
  pillActive: {
    backgroundColor: Design.colors.surface,
    borderWidth: 1,
    borderColor: Design.colors.outline,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  dotsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: 8,
    gap: 3,
  },
  thinkingDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: Design.colors.primary,
  },
  text: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 14,
    color: Design.colors.text.hint,
    fontWeight: '500',
  },
  textActive: {
    color: Design.colors.text.primary,
    fontWeight: '600',
  },
});
