import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Design } from '../constants/Design';

interface StatusBarProps {
  status: 'listening' | 'processing' | 'idle';
}

export const StatusBar: React.FC<StatusBarProps> = ({ status }) => {
  const getStatusText = () => {
    switch (status) {
      case 'listening': return '正在聆听...';
      case 'processing': return '正在处理...';
      default: return '已就绪';
    }
  };

  return (
    <View style={styles.container}>
      <View style={[styles.indicator, { backgroundColor: status === 'listening' ? Design.colors.happyBg : Design.colors.outline }]} />
      <Text style={styles.text}>{getStatusText()}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    height: 60,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Design.colors.surfaceContainer,
    borderBottomWidth: 1,
    borderBottomColor: Design.colors.outlineVariant,
  },
  indicator: {
    width: 12,
    height: 12,
    borderRadius: 6,
    marginRight: 10,
  },
  text: {
    fontFamily: Design.typography.fontFamily,
    ...Design.typography.headlineSmall,
    color: Design.colors.onSurface,
  },
});
