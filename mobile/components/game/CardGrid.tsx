import React, { useMemo } from 'react';
import { StyleSheet, View, useWindowDimensions } from 'react-native';

import MemoryCard, { CARD_MIN_SIZE } from './MemoryCard';
import { Design } from '@/constants/Design';
import { CARD_FACES } from '@/constants/MemoryGame';
import type { Card } from '@/hooks/useMemoryGame';

const GAP = 12;

/** 网格最大宽度。平板/桌面浏览器上不让牌摊得满屏都是，扫视距离太长反而更难记。 */
const MAX_GRID_WIDTH = 560;

const FACE_BY_ID = new Map(CARD_FACES.map((f) => [f.id, f]));

type Props = {
  cards: Card[];
  columns: number;
  isFlipped: (key: string) => boolean;
  onFlip: (key: string) => void;
};

export default function CardGrid({ cards, columns, isFlipped, onFlip }: Props) {
  const { width } = useWindowDimensions();

  const size = useMemo(() => {
    const available = Math.min(width, MAX_GRID_WIDTH) - Design.layout.innerPadding * 2;
    const raw = Math.floor((available - GAP * (columns - 1)) / columns);
    return Math.max(CARD_MIN_SIZE, raw);
  }, [width, columns]);

  return (
    <View style={[styles.grid, { width: columns * size + GAP * (columns - 1) }]}>
      {cards.map((card) => {
        const face = FACE_BY_ID.get(card.faceId);
        if (!face) return null;
        return (
          <MemoryCard
            key={card.key}
            face={face}
            faceUp={isFlipped(card.key)}
            matched={card.matched}
            size={size}
            onPress={() => onFlip(card.key)}
          />
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: GAP,
    alignSelf: 'center',
    justifyContent: 'center',
  },
});
