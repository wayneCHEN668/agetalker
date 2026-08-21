import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Design } from '@/constants/Design';
import { DECK_SIZES, type DeckSizeKey } from '@/constants/MemoryGame';

const ORDER: DeckSizeKey[] = ['few', 'normal', 'many'];

type Props = {
  value: DeckSizeKey;
  onChange: (key: DeckSizeKey) => void;
};

/**
 * 档位选择器。**常驻屏幕下方，不是进入游戏前的选择界面**——让老人每次进来
 * 先做一道选择题是额外的认知负担（spec §6）。
 *
 * 文案用「牌少一点/正好/牌多一点」而不是「简单/中等/困难」：后者逼他对自己的
 * 认知能力做评估。
 */
export default function DeckSizePicker({ value, onChange }: Props) {
  return (
    <View style={styles.row}>
      {ORDER.map((key) => {
        const deck = DECK_SIZES[key];
        const active = key === value;
        return (
          <Pressable
            key={key}
            onPress={() => onChange(key)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            accessibilityLabel={deck.label}
            style={[styles.option, active ? styles.optionActive : styles.optionIdle]}
          >
            <Text style={[styles.label, active ? styles.labelActive : styles.labelIdle]}>
              {deck.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: 6,
    justifyContent: 'center',
  },
  option: {
    minHeight: 48,
    paddingHorizontal: 12,
    justifyContent: 'center',
    borderRadius: Design.layout.radiusSmall,
    borderWidth: 1,
  },
  optionIdle: {
    backgroundColor: Design.colors.surface,
    borderColor: Design.colors.outline,
  },
  optionActive: {
    backgroundColor: Design.colors.primaryContainer,
    borderColor: Design.colors.primary,
  },
  label: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 15,
  },
  labelIdle: { color: Design.colors.text.secondary },
  labelActive: { color: Design.colors.onPrimaryContainer },
});
