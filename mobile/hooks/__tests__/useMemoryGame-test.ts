import { act, renderHook } from '@testing-library/react-native';
import { useMemoryGame, type Card } from '@/hooks/useMemoryGame';
import { DECK_SIZES, MISMATCH_HOLD_MS, type DeckSizeKey } from '@/constants/MemoryGame';

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

describe('错配后停留再翻回', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  test(`翻错后两张牌先留在正面（不足 ${MISMATCH_HOLD_MS}ms）`, () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    const [a, b] = findMismatch(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));

    // 老人反应慢，翻回太快他还没看清第二张就没了，这一轮信息等于白给
    act(() => { jest.advanceTimersByTime(MISMATCH_HOLD_MS - 100); });
    expect(result.current.isFlipped(a.key)).toBe(true);
    expect(result.current.isFlipped(b.key)).toBe(true);
  });

  test(`满 ${MISMATCH_HOLD_MS}ms 后两张一起翻回背面`, () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    const [a, b] = findMismatch(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));

    act(() => { jest.advanceTimersByTime(MISMATCH_HOLD_MS); });
    expect(result.current.isFlipped(a.key)).toBe(false);
    expect(result.current.isFlipped(b.key)).toBe(false);
  });

  test('翻错不产生任何 matched（没有"错误"惩罚，也没有奖励）', () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    const [a, b] = findMismatch(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));
    act(() => { jest.advanceTimersByTime(MISMATCH_HOLD_MS); });

    expect(result.current.cards.every((c) => !c.matched)).toBe(true);
  });
});

describe('判定期锁定', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  test('停留窗口内的第三次点击被忽略', () => {
    // 手抖连点：不锁的话第三张牌会覆盖 flipped，状态机错乱
    const { result } = renderHook(() => useMemoryGame('normal'));
    const [a, b] = findMismatch(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));

    const third = result.current.cards.find((c) => c.key !== a.key && c.key !== b.key);
    if (!third) throw new Error('测试前提被破坏：牌堆不足三张');
    act(() => result.current.flip(third.key));
    expect(result.current.isFlipped(third.key)).toBe(false);
  });

  test('停留结束后又能正常翻牌', () => {
    const { result } = renderHook(() => useMemoryGame('normal'));
    const [a, b] = findMismatch(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));
    act(() => { jest.advanceTimersByTime(MISMATCH_HOLD_MS); });

    const third = result.current.cards.find((c) => c.key !== a.key && c.key !== b.key);
    if (!third) throw new Error('测试前提被破坏：牌堆不足三张');
    act(() => result.current.flip(third.key));
    expect(result.current.isFlipped(third.key)).toBe(true);
  });
});

describe('换档位', () => {
  test('换档位后牌数变为新档位、重新洗牌、配对状态清空', () => {
    const { result, rerender } = renderHook(
      ({ size }: { size: DeckSizeKey }) => useMemoryGame(size),
      { initialProps: { size: 'few' as DeckSizeKey } },
    );

    const [a, b] = findPair(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));
    expect(result.current.cards.some((c) => c.matched)).toBe(true);

    rerender({ size: 'many' as DeckSizeKey });

    expect(result.current.cards).toHaveLength(DECK_SIZES.many.cardCount);
    expect(result.current.cards.every((c) => !c.matched)).toBe(true);
    expect(result.current.status).toBe('playing');
  });

  test('档位没变时不重新发牌（不会把玩到一半的局洗掉）', () => {
    const { result, rerender } = renderHook(
      ({ size }: { size: DeckSizeKey }) => useMemoryGame(size),
      { initialProps: { size: 'normal' as DeckSizeKey } },
    );

    const [a, b] = findPair(result.current.cards);
    act(() => result.current.flip(a.key));
    act(() => result.current.flip(b.key));

    rerender({ size: 'normal' as DeckSizeKey });
    expect(result.current.cards.some((c) => c.matched)).toBe(true);
  });
});
