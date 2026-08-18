import React, { useCallback, useEffect, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

import CardGrid from '@/components/game/CardGrid';
import DeckSizePicker from '@/components/game/DeckSizePicker';
import RoundComplete from '@/components/game/RoundComplete';
import { Design } from '@/constants/Design';
import {
  DECK_SIZES,
  DECK_SIZE_STORAGE_KEY,
  DEFAULT_DECK_SIZE,
  isDeckSizeKey,
  type DeckSizeKey,
} from '@/constants/MemoryGame';
import { useMemoryGame } from '@/hooks/useMemoryGame';

export default function BrainGameScreen() {
  // null = 还在读存储。读完之前不渲染牌桌，免得先闪一副默认档位的牌再换掉。
  const [deckSize, setDeckSize] = useState<DeckSizeKey | null>(null);

  useEffect(() => {
    let alive = true;
    AsyncStorage.getItem(DECK_SIZE_STORAGE_KEY)
      .then((stored) => {
        if (!alive) return;
        setDeckSize(isDeckSizeKey(stored) ? stored : DEFAULT_DECK_SIZE);
      })
      .catch(() => {
        // 存储读不出来不是错误，用默认档位继续——这个游戏不该因为存储问题打不开
        if (alive) setDeckSize(DEFAULT_DECK_SIZE);
      });
    return () => {
      alive = false;
    };
  }, []);

  const handleChangeDeckSize = useCallback((key: DeckSizeKey) => {
    setDeckSize(key);
    // 写失败就写失败，下次用默认档位，不打扰他
    AsyncStorage.setItem(DECK_SIZE_STORAGE_KEY, key).catch(() => {});
  }, []);

  // 读存储通常几毫秒，不放 loading spinner——一闪而过的转圈比空白更烦
  if (deckSize === null) {
    return <View style={styles.screen} />;
  }

  return <GameBoard deckSize={deckSize} onChangeDeckSize={handleChangeDeckSize} />;
}

type GameBoardProps = {
  deckSize: DeckSizeKey;
  onChangeDeckSize: (key: DeckSizeKey) => void;
};

/**
 * 牌桌。单独成组件是因为 useMemoryGame 需要一个非 null 的 deckSize，
 * 而 hook 不能写在条件分支里。
 */
function GameBoard({ deckSize, onChangeDeckSize }: GameBoardProps) {
  const { cards, status, isFlipped, flip, restart } = useMemoryGame(deckSize);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.board}>
        {status === 'complete' ? (
          <RoundComplete onRestart={restart} />
        ) : (
          <CardGrid
            cards={cards}
            columns={DECK_SIZES[deckSize].columns}
            isFlipped={isFlipped}
            onFlip={flip}
          />
        )}
      </View>

      <DeckSizePicker value={deckSize} onChange={onChangeDeckSize} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Design.colors.background,
  },
  content: {
    flexGrow: 1,
    paddingVertical: Design.layout.spacing,
    paddingHorizontal: Design.layout.innerPadding,
    gap: Design.layout.spacing,
    justifyContent: 'center',
  },
  board: {
    justifyContent: 'center',
    alignItems: 'center',
  },
});
