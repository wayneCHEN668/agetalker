import React, { useEffect, useRef } from 'react';
import { TouchableOpacity, Text, StyleSheet, View, Animated } from 'react-native';
import { Design } from '../constants/Design';

interface ActionButtonProps {
  isRecording: boolean;
  onPress: () => void;
}

export const ActionButton: React.FC<ActionButtonProps> = ({ isRecording, onPress }) => {
  const pulseAnim = useRef(new Animated.Value(1)).current;
  const pressAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (isRecording) {
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, {
            toValue: 1.04,
            duration: 600,
            useNativeDriver: true,
          }),
          Animated.timing(pulseAnim, {
            toValue: 1,
            duration: 600,
            useNativeDriver: true,
          }),
        ]),
      );
      loop.start();
      return () => loop.stop();
    } else {
      pulseAnim.setValue(1);
      pressAnim.setValue(1);
    }
  }, [isRecording]);

  const handlePressIn = () => {
    Animated.spring(pressAnim, {
      toValue: 0.96,
      useNativeDriver: true,
    }).start();
  };

  const handlePressOut = () => {
    Animated.spring(pressAnim, {
      toValue: 1,
      useNativeDriver: true,
    }).start();
  };

  const bgColor = isRecording ? Design.colors.recording : Design.colors.primary;

  return (
    <View style={styles.container}>
      <Animated.View
        style={[
          styles.button,
          { backgroundColor: bgColor },
          { transform: [{ scale: Animated.multiply(pulseAnim, pressAnim) }] },
        ]}
      >
        <TouchableOpacity
          style={styles.touchable}
          onPress={onPress}
          onPressIn={handlePressIn}
          onPressOut={handlePressOut}
          activeOpacity={1}
          accessibilityRole="button"
          accessibilityLabel={isRecording ? '挂断' : '点击说话'}
        >
          <Text style={styles.icon}>{isRecording ? '⊚' : '♪'}</Text>
          <Text style={styles.text}>{isRecording ? '挂断' : '点击说话'}</Text>
        </TouchableOpacity>
      </Animated.View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    paddingBottom: 48,
    paddingHorizontal: Design.layout.spacing * 2,
  },
  button: {
    width: '100%',
    maxWidth: 320,
    height: 80,
    borderRadius: 40,
    shadowColor: Design.colors.primary,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.2,
    shadowRadius: 16,
    elevation: 10,
    overflow: 'hidden',
  },
  touchable: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    borderRadius: 40,
  },
  icon: {
    fontSize: 22,
    color: '#FFFFFF',
    opacity: 0.9,
  },
  text: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 22,
    color: '#FFFFFF',
    fontWeight: '700',
    letterSpacing: 1.5,
  },
});
