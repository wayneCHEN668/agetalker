import { renderHook } from '@testing-library/react-native';
import { useMemoryGame } from '@/hooks/useMemoryGame';
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
