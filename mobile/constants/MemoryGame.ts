import type { ComponentProps } from 'react';
import type { MaterialCommunityIcons } from '@expo/vector-icons';

export type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];

export type CardFace = {
  /** 配对判定依据。同一 face 的两张牌 faceId 相同、key 不同。 */
  id: string;
  icon: IconName;
  /** 中文词，显示在图标下方。图标是通用老物件，年代感靠这个词补。 */
  zh: string;
};

/**
 * 老物件素材库。
 *
 * 下面 16 个图标名已逐个核对过 MaterialCommunityIcons 的 glyphmap（共 7448 个图标），
 * 全部真实存在。新增条目必须同样核对——MemoryGame-test.ts 会挡住没核对的。
 *
 * 已确认**不存在**的名字，别再试：teapot、sewing-machine、gramophone、
 * camera-retro、pocket-watch。对应替代见下表。
 */
export const CARD_FACES: CardFace[] = [
  { id: 'radio',      icon: 'radio',          zh: '收音机' },
  { id: 'abacus',     icon: 'abacus',         zh: '算盘'   },
  { id: 'gramophone', icon: 'record-player',  zh: '留声机' },
  { id: 'typewriter', icon: 'typewriter',     zh: '打字机' },
  { id: 'kettle',     icon: 'kettle',         zh: '水壶'   },
  { id: 'tea',        icon: 'tea',            zh: '茶杯'   },
  { id: 'fan',        icon: 'fan',            zh: '蒲扇'   },
  { id: 'pen',        icon: 'fountain-pen',   zh: '钢笔'   },
  { id: 'basket',     icon: 'basket-outline', zh: '竹篮'   },
  { id: 'lamp',       icon: 'lamp',           zh: '台灯'   },
  { id: 'umbrella',   icon: 'umbrella',       zh: '雨伞'   },
  { id: 'stool',      icon: 'stool',          zh: '板凳'   },
  { id: 'needle',     icon: 'needle',         zh: '针线'   },
  { id: 'key',        icon: 'key-variant',    zh: '钥匙'   },
  { id: 'phone',      icon: 'phone-classic',  zh: '座机'   },
  { id: 'bicycle',    icon: 'bicycle',        zh: '自行车' },
];

export type DeckSizeKey = 'few' | 'normal' | 'many';

export type DeckSize = {
  key: DeckSizeKey;
  label: string;
  cardCount: number;
  columns: number;
};

/**
 * 档位。文案刻意避开「简单/困难」——让老人评估自己的认知能力这件事本身就是伤害。
 * 大档定在 16 张（4×4）而不是 20 张（4×5）：20 张时手机竖屏单卡约 70px，中文词读不清，
 * 而看不清的牌面对这个用户群等于没有。
 */
export const DECK_SIZES: Record<DeckSizeKey, DeckSize> = {
  few:    { key: 'few',    label: '牌少一点', cardCount: 6,  columns: 2 },
  normal: { key: 'normal', label: '正好',     cardCount: 12, columns: 3 },
  many:   { key: 'many',   label: '牌多一点', cardCount: 16, columns: 4 },
};

export const DEFAULT_DECK_SIZE: DeckSizeKey = 'normal';

/**
 * 翻错后两张牌停留多久再翻回。
 * 老人反应慢，翻回太快他还没看清第二张牌就消失了，这一轮的信息等于白给。
 * 此值需要真实老人测试后调整。
 */
export const MISMATCH_HOLD_MS = 1200;

export const DECK_SIZE_STORAGE_KEY = 'memoryGame.deckSize';

export function isDeckSizeKey(v: unknown): v is DeckSizeKey {
  return typeof v === 'string' && v in DECK_SIZES;
}
