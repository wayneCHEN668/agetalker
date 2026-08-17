import { act, renderHook } from '@testing-library/react-native';
import { useMemoryGame, type Card } from '@/hooks/useMemoryGame';
import { DECK_SIZES, type DeckSizeKey } from '@/constants/MemoryGame';

const ALL_SIZES: DeckSizeKey[] = ['few', 'normal', 'many'];

describe.each(ALL_SIZES)('发牌（档位 %s）', (size) => {
  test('牌数等于档位设定', () => {
    const { result } = renderHook(() => useMemoryGame(size));
    expect(result.current.cards).toHaveLength(DECK_SIZES[size].cardCount);
  });

  test('每种图案恰好两张', () => {
    const { result } = renderHook(() => useMemoryGame(size));
    const counts = new Map<string, number>();
    for (const c of result.current.cards) {
      counts.set(c.faceId, (counts.get(c.faceId) ?? 0) + 1);
    }
    expect(counts.size).toBe(DECK_SIZES[size].cardCount / 2);
    expect([...counts.values()].every((n) => n === 2)).toBe(true);
  });

  test('每张牌的 key 唯一', () => {
    const { result } = renderHook(() => useMemoryGame(size));
    const keys = result.current.cards.map((c) => c.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe('初始状态', () => {
  test('状态是 playing', () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    expect(result.current.status).toBe('playing');
  });

  test('没有已配对的牌', () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    expect(result.current.cards.every((c) => !c.matched)).toBe(true);
  });

  test('没有翻开的牌', () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    expect(result.current.cards.every((c) => !result.current.isFlipped(c.key))).toBe(true);
  });
});

/** 从牌堆里找一对同图案的牌。洗牌是随机的，所以按 faceId 现找而不是写死下标。 */
function findPair(cards: Card[]): [Card, Card] {
  const first = cards[0];
  const second = cards.find((c) => c.faceId === first.faceId && c.key !== first.key);
  if (!second) throw new Error('测试前提被破坏：牌堆里没有成对的牌');
  return [first, second];
}

/** 找两张不同图案的牌。 */
function findMismatch(cards: Card[]): [Card, Card] {
  const first = cards[0];
  const other = cards.find((c) => c.faceId !== first.faceId);
  if (!other) throw new Error('测试前提被破坏：牌堆里只有一种图案');
  return [first, other];
}

describe('翻牌与配对判定', () => {
  test('翻开一张牌后它正面朝上', () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    const target = result.current.cards[0];
    act(() => result.current.flip(target.key));
    expect(result.current.isFlipped(target.key)).toBe(true);
  });

  test('翻开两张相同图案 → 两张都标记为 matched', () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    const [a, b] = findPair(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));

    const byKey = new Map(result.current.cards.map((c) => [c.key, c]));
    expect(byKey.get(a.key)?.matched).toBe(true);
    expect(byKey.get(b.key)?.matched).toBe(true);
  });

  test('配对成功的牌永久正面朝上（不移除、不翻回）', () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    const [a, b] = findPair(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));

    expect(result.current.cards).toHaveLength(DECK_SIZES.normal.cardCount);
    expect(result.current.isFlipped(a.key)).toBe(true);
    expect(result.current.isFlipped(b.key)).toBe(true);
  });

  test('重复点同一张已翻开的牌不产生配对', () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    const target = result.current.cards[0];
    act(() => result.current.flip(target.key));
    act(() => result.current.flip(target.key));

    const card = result.current.cards.find((c) => c.key === target.key);
    expect(card?.matched).toBe(false);
  });

  test('点击已配对的牌不改变任何状态', () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    const [a, b] = findPair(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));

    const before = result.current.cards.filter((c) => c.matched).length;
    act(() => result.current.flip(a.key));
    expect(result.current.cards.filter((c) => c.matched).length).toBe(before);
  });
});

describe('完成态', () => {
  test('全部配对后状态转为 complete', () => {
    const { result } = renderHook(() => useMemoryGame('few'));
    const faceIds = [...new Set(result.current.cards.map((c) => c.faceId))];

    for (const faceId of faceIds) {
      const pair = result.current.cards.filter((c) => c.faceId === faceId);
      act(() => result.current.flip(pair[0].key));
      act(() => result.current.flip(pair[1].key));
    }

    expect(result.current.cards.every((c) => c.matched)).toBe(true);
    expect(result.current.status).toBe('complete');
  });

  test('还剩一对没配上时不是 complete', () => {
    const { result } = renderHook(() => useMemoryGame('few'));
    const faceIds = [...new Set(result.current.cards.map((c) => c.faceId))];

    for (const faceId of faceIds.slice(0, -1)) {
      const pair = result.current.cards.filter((c) => c.faceId === faceId);
      act(() => result.current.flip(pair[0].key));
      act(() => result.current.flip(pair[1].key));
    }

    expect(result.current.status).toBe('playing');
  });

  test('restart 之后重新发牌、清空配对状态', () => {
    const { result } = renderHook(() => useMemoryGame('few'));
    const [a, b] = findPair(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));
    expect(result.current.cards.some((c) => c.matched)).toBe(true);

    act(() => result.current.restart());
    expect(result.current.cards.every((c) => !c.matched)).toBe(true);
    expect(result.current.status).toBe('playing');
    expect(result.current.cards).toHaveLength(DECK_SIZES.few.cardCount);
  });
});
