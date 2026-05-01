import React from 'react';
import { TouchableOpacity, Text, StyleSheet, View } from 'react-native';
import { Design } from '../constants/Design';

interface ActionButtonProps {
  isRecording: boolean;
  onPress: () => void;
}

export const ActionButton: React.FC<ActionButtonProps> = ({ isRecording, onPress }) => {
  return (
    <View style={styles.container}>
      <TouchableOpacity
        style={[
          styles.button, 
          { backgroundColor: isRecording ? '#ba1a1a' : Design.colors.primary }
        ]}
        onPress={onPress}
        activeOpacity={0.9}
      >
        <Text style={styles.text}>{isRecording ? "挂断" : "点击说话"}</Text>
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: Design.layout.spacing * 2, // More side padding for a more compact button
    paddingBottom: 40,
  },
  button: {
    height: 72,
    borderRadius: 36,
    alignItems: 'center',
    justifyContent: 'center',
    // Ultra-premium tactile shadow
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 8,
  },
  text: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 20,
    color: '#ffffff',
    fontWeight: '700',
    letterSpacing: 1,
  },
});
