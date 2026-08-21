import React, { useEffect, useRef } from 'react';
import { Animated, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Design } from '../constants/Design';

interface ErrorToastProps {
  message: string;
  visible: boolean;
  onDismiss: () => void;
  duration?: number; // ms, default 5000
}

export const ErrorToast: React.FC<ErrorToastProps> = ({
  message,
  visible,
  onDismiss,
  duration = 5000,
}) => {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(20)).current;

  useEffect(() => {
    if (visible) {
      Animated.parallel([
        Animated.timing(opacity, {
          toValue: 1,
          duration: 250,
          useNativeDriver: true,
        }),
        Animated.timing(translateY, {
          toValue: 0,
          duration: 250,
          useNativeDriver: true,
        }),
      ]).start();

      const timer = setTimeout(() => {
        hide();
      }, duration);
      return () => clearTimeout(timer);
    } else {
      opacity.setValue(0);
      translateY.setValue(20);
    }
  }, [visible, message]);

  const hide = () => {
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 0,
        duration: 300,
        useNativeDriver: true,
      }),
      Animated.timing(translateY, {
        toValue: 20,
        duration: 300,
        useNativeDriver: true,
      }),
    ]).start(() => onDismiss());
  };

  if (!visible) return null;

  return (
    <Animated.View
      style={[
        styles.container,
        { opacity, transform: [{ translateY }] },
      ]}
    >
      <TouchableOpacity
        style={styles.toast}
        onPress={hide}
        activeOpacity={0.9}
        accessibilityRole="alert"
        accessibilityLabel={message}
      >
        <Text style={styles.icon}>⚠</Text>
        <Text style={styles.text} numberOfLines={2}>
          {message}
        </Text>
        <TouchableOpacity onPress={hide} style={styles.closeBtn}>
          <Text style={styles.closeText}>知道了</Text>
        </TouchableOpacity>
      </TouchableOpacity>
    </Animated.View>
  );
};

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    bottom: 140,
    left: 24,
    right: 24,
    alignItems: 'center',
    zIndex: 100,
  },
  toast: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Design.colors.surface,
    borderRadius: Design.layout.radius,
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderWidth: 1,
    borderColor: Design.colors.outline,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 6,
    maxWidth: 400,
  },
  icon: {
    fontSize: 20,
    marginRight: 10,
    color: Design.colors.primary,
  },
  text: {
    flex: 1,
    fontFamily: Design.typography.fontFamily,
    fontSize: 16,
    lineHeight: 24,
    color: Design.colors.text.primary,
  },
  closeBtn: {
    marginLeft: 12,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: Design.layout.radiusSmall,
    backgroundColor: Design.colors.primaryContainer,
  },
  closeText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 14,
    color: Design.colors.primary,
    fontWeight: '600',
  },
});
