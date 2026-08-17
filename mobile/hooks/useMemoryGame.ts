import { useCallback, useMemo, useState } from 'react';

import { CARD_FACES, DECK_SIZES, type DeckSizeKey } from '@/constants/MemoryGame';

export type Card = {
  /** 这张牌的唯一标识。同一图案的两张牌 key 不同。 */
  key: string;
  /** 配对判定依据。同一图案的两张牌 faceId 相同。 */
  faceId: string;
  matched: boolean;
};

export type GameStatus = 'playing' | 'complete';

function shuffle<T>(items: T[]): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** 按档位发一副牌：先随机选够对数的图案，每个图案两张，再整体洗一次。 */
export function buildDeck(deckSize: DeckSizeKey): Card[] {
  const pairCount = DECK_SIZES[deckSize].cardCount / 2;
  const faces = shuffle(CARD_FACES).slice(0, pairCount);
  const cards = faces.flatMap((f) => [
    { key: `${f.id}-a`, faceId: f.id, matched: false },
    { key: `${f.id}-b`, faceId: f.id, matched: false },
  ]);
  return shuffle(cards);
}

export function useMemoryGame(deckSize: DeckSizeKey) {
  const [cards, setCards] = useState<Card[]>(() => buildDeck(deckSize));
  const [flipped, setFlipped] = useState<string[]>([]);

  const status: GameStatus =
    cards.length > 0 && cards.every((c) => c.matched) ? 'complete' : 'playing';

  const matchedKeys = useMemo(
    () => new Set(cards.filter((c) => c.matched).map((c) => c.key)),
    [cards],
  );

  /** 一张牌该不该正面朝上：要么刚被翻开还没判定，要么已经配对成功。 */
  const isFlipped = useCallback(
    (key: string) => flipped.includes(key) || matchedKeys.has(key),
    [flipped, matchedKeys],
  );

  const restart = useCallback(() => {
    setCards(buildDeck(deckSize));
    setFlipped([]);
  }, [deckSize]);

  const flip = useCallback(
    (key: string) => {
      if (flipped.includes(key)) return;

      const card = cards.find((c) => c.key === key);
      // 已配对的牌永久正面朝上，再点它没有任何意义
      if (!card || card.matched) return;

      const next = [...flipped, key];
      setFlipped(next);
      if (next.length < 2) return;

      const [aKey, bKey] = next;
      const a = cards.find((c) => c.key === aKey);
      const b = cards.find((c) => c.key === bKey);
      if (!a || !b) return;

      if (a.faceId === b.faceId) {
        setCards((cs) =>
          cs.map((c) => (c.key === aKey || c.key === bKey ? { ...c, matched: true } : c)),
        );
        // 清空 flipped：这两张牌之后靠 matched 保持正面朝上
        setFlipped([]);
      }
      // 不匹配的分支在 Task 5 补（停留 MISMATCH_HOLD_MS 后翻回）
    },
    [cards, flipped],
  );

  return { cards, status, isFlipped, flip, restart };
}
