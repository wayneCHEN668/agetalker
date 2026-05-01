import React from 'react';
import { TouchableOpacity, Text, StyleSheet } from 'react-native';
import { Design } from '../constants/Design';

interface ActionButtonProps {
  isRecording: boolean;
  onPress: () => void;
}

export const ActionButton: React.FC<ActionButtonProps> = ({ isRecording, onPress }) => {
  return (
    <TouchableOpacity
      style={[styles.button, { backgroundColor: isRecording ? Design.colors.error : Design.colors.primary }]}
      onPress={onPress}
      activeOpacity={0.8}
    >
      <Text style={styles.text}>{isRecording ? "挂断" : "开始对话"}</Text>
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  button: {
    height: 80,
    marginHorizontal: Design.layout.spacing,
    marginBottom: Design.layout.spacing,
    borderRadius: 40,
    alignItems: 'center',
    justifyContent: 'center',
    elevation: 4,
    boxShadow: '0px 2px 3.84px rgba(0, 0, 0, 0.25)',
  },
  text: {
    fontFamily: Design.typography.fontFamily,
    ...Design.typography.headlineMedium,
    color: '#ffffff',
    fontWeight: 'bold',
  },
});
