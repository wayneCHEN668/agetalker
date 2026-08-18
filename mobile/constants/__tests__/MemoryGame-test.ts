import { MaterialCommunityIcons } from '@expo/vector-icons';
import {
  CARD_FACES,
  DECK_SIZES,
  DEFAULT_DECK_SIZE,
  MISMATCH_HOLD_MS,
  isDeckSizeKey,
} from '@/constants/MemoryGame';

describe('卡面素材库', () => {
  test('数量够最大档位发牌', () => {
    const maxPairs = Math.max(...Object.values(DECK_SIZES).map((d) => d.cardCount)) / 2;
    expect(CARD_FACES.length).toBeGreaterThanOrEqual(maxPairs);
  });

  test('id 唯一', () => {
    const ids = CARD_FACES.map((f) => f.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test('每个图标名在 MaterialCommunityIcons 里真实存在', () => {
    // 猜一个不存在的图标名不会报错，只会渲染成空白方块，
    // 在 70px 的小卡片上肉眼极难发现。这条断言就是那双眼睛。
    const glyphs = MaterialCommunityIcons.glyphMap as Record<string, number>;
    const missing = CARD_FACES.filter((f) => !(f.icon in glyphs)).map((f) => f.icon);
    expect(missing).toEqual([]);
  });

  test('每个卡面都有中文词', () => {
    expect(CARD_FACES.every((f) => f.zh.trim().length > 0)).toBe(true);
  });
});

describe('档位', () => {
  test('牌数是偶数（要成对），且能被列数整除（网格要填满）', () => {
    for (const d of Object.values(DECK_SIZES)) {
      expect(d.cardCount % 2).toBe(0);
      expect(d.cardCount % d.columns).toBe(0);
    }
  });

  test('文案不出现能力评判词', () => {
    // 「简单/困难」会逼老人对自己的认知能力做评估，这是设计上刻意避开的。
    // 这条断言防止它日后被"顺手改得更清楚"改回去。
    const labels = Object.values(DECK_SIZES).map((d) => d.label).join('');
    expect(labels).not.toMatch(/简单|困难|容易|难/);
  });

  test('默认档位存在于档位表里', () => {
    expect(DECK_SIZES[DEFAULT_DECK_SIZE]).toBeDefined();
  });

  test('isDeckSizeKey 认得合法值、挡得住非法值', () => {
    expect(isDeckSizeKey('normal')).toBe(true);
    expect(isDeckSizeKey('few')).toBe(true);
    expect(isDeckSizeKey('nonsense')).toBe(false);
    expect(isDeckSizeKey(null)).toBe(false);
    expect(isDeckSizeKey(12)).toBe(false);
  });
});

test('错配停留时长是具名常量且为正数', () => {
  expect(MISMATCH_HOLD_MS).toBeGreaterThan(0);
});
