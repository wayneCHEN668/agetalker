import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Design } from '../constants/Design';

interface StatusBarProps {
  status: 'listening' | 'processing' | 'idle';
}

export const StatusBar: React.FC<StatusBarProps> = ({ status }) => {
  const getStatusText = () => {
    switch (status) {
      case 'listening': return '正在聆听';
      case 'processing': return '思考中';
      default: return 'AgeTalker 已就绪';
    }
  };

  return (
    <View style={styles.container}>
      <View style={[
        styles.indicator, 
        { backgroundColor: status === 'listening' ? '#FFD54F' : Design.colors.outline }
      ]} />
      <Text style={styles.text}>{getStatusText()}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    height: 30, // Reduced by half
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.03)',
  },
  indicator: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  text: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 12,
    fontWeight: '600',
    color: Design.colors.text.secondary,
    letterSpacing: 0.5,
  },
});
