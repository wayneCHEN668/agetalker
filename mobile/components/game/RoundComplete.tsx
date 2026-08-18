import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Design } from '@/constants/Design';

/**
 * 收尾语。**不含任何成绩信息**——没有用时、没有翻牌次数、没有"打败了百分之几"。
 * 报数字就是在评判他，而这个游戏从头到尾不评判。
 */
const PRAISE = ['都配上了，真不错。', '全找着了，眼神真好。', '这一局稳稳的。'];

type Props = {
  onRestart: () => void;
};

export default function RoundComplete({ onRestart }: Props) {
  // 每次挂载随机挑一句，避免每局都是同一句话
  const [line] = useState(() => PRAISE[Math.floor(Math.random() * PRAISE.length)]);

  return (
    <View style={styles.wrap}>
      <Text style={styles.line}>{line}</Text>
      <Pressable
        onPress={onRestart}
        accessibilityRole="button"
        accessibilityLabel="再来一局"
        style={styles.button}
      >
        <Text style={styles.buttonText}>再来一局</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    gap: 16,
  },
  line: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.headline.fontSize,
    lineHeight: Design.typography.headline.lineHeight,
    color: Design.colors.text.primary,
    textAlign: 'center',
  },
  button: {
    minHeight: 64,
    paddingHorizontal: 36,
    justifyContent: 'center',
    borderRadius: Design.layout.radius,
    backgroundColor: Design.colors.primary,
  },
  buttonText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 20,
    color: Design.colors.onPrimary,
  },
});
