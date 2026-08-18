# 练练脑：年代主题翻牌配对游戏 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `app/(tabs)/two.tsx` 的 Expo 默认模板替换成一个年代主题的翻牌配对游戏，供养老院老人锻炼短期记忆。

**Architecture:** 纯前端自包含，不碰后端、不碰聊天 tab、断网可玩。游戏规则全部收敛在一个零 RN 依赖的纯逻辑 hook `useMemoryGame` 里（可单元测试），UI 组件只是它的投影。卡面用 `@expo/vector-icons` 的老物件图标 + 中文词，只作视觉皮肤，游戏本身不问「这是什么」。

**Tech Stack:** React Native 0.81 / React 19 / Expo 54 / expo-router / TypeScript / AsyncStorage / jest-expo + @testing-library/react-native

**Spec:** `docs/superpowers/specs/2026-08-18-memory-card-game-design.md`

## Global Constraints

每个任务的要求都隐含包含本节。数值一律从 spec 逐字抄来。

- **无计时、无分数、无「错误」提示、无失败态。** 翻错的唯一表现是牌翻回去：不变红、不震动、不出声、不计次。
- **完成时不显示用时、不显示翻牌次数。**
- **点击区 ≥ 64×64 px**（远超 44 的通用无障碍标准，因为目标用户手抖）。
- **所有颜色、字号、圆角走 `constants/Design.ts`**，不新造设计 token。
- **`hooks/useMemoryGame.ts` 不得 import 任何 React Native 组件**，只能是状态 + 纯函数。这是可测性的前提。
- **档位文案严格用「牌少一点 / 正好 / 牌多一点」**，禁止出现「简单 / 困难 / 容易 / 难」——不逼老人对自己的能力做评估。
- **图标名必须在 `MaterialCommunityIcons.glyphMap` 中真实存在。** 猜一个名字渲染出来是空白方块，在小卡片上肉眼很难发现。
- **档位定义**：`few` = 6 张 2 列 / `normal` = 12 张 3 列 / `many` = 16 张 4 列。默认 `normal`。
- **`MISMATCH_HOLD_MS = 1200`**（翻错后停留多久再翻回）。必须是具名常量，不得内联为魔数。
- **配对成功的牌永久留在场上正面朝上，不移除**（移除会导致布局跳动，老人丢失空间记忆锚点）。

---

### Task 1: Jest 测试基础设施

前端目前跑不了任何测试：`components/__tests__/StyledText-test.js` 是 Expo 模板遗留，`package.json` 里既无 jest 配置也无 `test` 脚本。本任务先把测试跑通，因为后面三个任务全部是 TDD。

本任务的 smoke test 不是走过场：项目**没有 `babel.config.js`**，`@/` 路径别名靠 `babel-preset-expo` 内建的 tsconfig paths 支持，而 **jest 不会自动继承这个解析规则**。这是最容易在这里踩的坑，smoke test 就是用来把它钉死的。

**Files:**
- Create: `mobile/jest.config.js`
- Create: `mobile/__tests__/jest-setup-smoke-test.ts`
- Modify: `mobile/package.json`（加 `test` 脚本与 devDependencies）

**Interfaces:**
- Consumes: 无（首个任务）
- Produces: 可用的 `npm test` 命令（在 `mobile/` 下运行 jest）；`@/` 别名在测试中可解析

- [ ] **Step 1: 写 smoke test**

创建 `mobile/__tests__/jest-setup-smoke-test.ts`：

```ts
// 这个测试守的不是 Design.ts，是 jest 的模块解析配置。
// 本项目没有 babel.config.js，`@/` 别名靠 babel-preset-expo 内建的 tsconfig
// paths 支持，jest 不会自动继承——必须在 jest.config.js 里显式 moduleNameMapper。
// 哪天有人删掉那行映射，这个测试会立刻红，而不是等到某个业务测试莫名其妙挂掉。
import { Design } from '@/constants/Design';

test('jest 能解析 @/ 路径别名', () => {
  expect(Design.colors.primary).toBe('#C17B6A');
});

test('jest 环境能跑 TypeScript', () => {
  const n: number = 1 + 1;
  expect(n).toBe(2);
});
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd mobile && npm test
```

预期：FAIL —— `npm error Missing script: "test"`（`test` 脚本还不存在）。

- [ ] **Step 3: 安装测试依赖**

用 `expo install` 而不是 `npm install`，它会挑选与 Expo 54 兼容的版本：

```bash
cd mobile && npx expo install -- --save-dev jest-expo jest @testing-library/react-native
```

- [ ] **Step 4: 创建 jest 配置**

创建 `mobile/jest.config.js`：

```js
module.exports = {
  preset: 'jest-expo',
  moduleNameMapper: {
    // tsconfig.json 里 "@/*" -> "./*"。jest 不读 tsconfig paths，必须在这里重复一遍。
    '^@/(.*)$': '<rootDir>/$1',
  },
  transformIgnorePatterns: [
    'node_modules/(?!((jest-)?react-native|@react-native(-community)?|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|react-navigation|@react-navigation/.*|@testing-library/react-native))',
  ],
};
```

- [ ] **Step 5: 加 test 脚本**

在 `mobile/package.json` 的 `scripts` 里加一行（放在 `"web"` 之后）：

```json
    "test": "jest"
```

- [ ] **Step 6: 运行，确认通过**

```bash
cd mobile && npm test
```

预期：PASS，2 个测试通过。

若 `jest-expo` 与 React 19 报 peer 冲突或 transform 报错，先只解决报错本身，**不要**为了绕开而改用其它 preset。若 30 分钟内无法跑通，停下来向发起人报告——spec §10.3 已把这条列为已知风险，退路是保持 hook 的纯逻辑性质、测试后补。

- [ ] **Step 7: 提交**

```bash
cd mobile && git add jest.config.js package.json package-lock.json __tests__/jest-setup-smoke-test.ts
git commit -m "test: 接入 jest-expo，锁定 @/ 别名解析

前端此前没有可用的 test runner。后面的游戏状态机是纯逻辑，正是最该测
也最好测的部分，先把跑测试这件事解决掉。

smoke test 守的是模块解析：本项目没有 babel.config.js，@/ 别名靠
babel-preset-expo 内建支持，jest 不继承，必须显式 moduleNameMapper。"
```

---

### Task 2: 卡面素材库与档位常量

**Files:**
- Create: `mobile/constants/MemoryGame.ts`
- Create: `mobile/constants/__tests__/MemoryGame-test.ts`

**Interfaces:**
- Consumes: Task 1 的 `npm test`
- Produces:
  - `type CardFace = { id: string; icon: IconName; zh: string }`
  - `type DeckSizeKey = 'few' | 'normal' | 'many'`
  - `type DeckSize = { key: DeckSizeKey; label: string; cardCount: number; columns: number }`
  - `const CARD_FACES: CardFace[]`（16 项）
  - `const DECK_SIZES: Record<DeckSizeKey, DeckSize>`
  - `const DEFAULT_DECK_SIZE: DeckSizeKey`
  - `const MISMATCH_HOLD_MS: number`
  - `const DECK_SIZE_STORAGE_KEY: string`
  - `function isDeckSizeKey(v: unknown): v is DeckSizeKey`

- [ ] **Step 1: 写失败的测试**

创建 `mobile/constants/__tests__/MemoryGame-test.ts`：

```ts
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
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd mobile && npx jest constants/__tests__/MemoryGame-test.ts
```

预期：FAIL —— `Cannot find module '@/constants/MemoryGame'`。

- [ ] **Step 3: 写实现**

创建 `mobile/constants/MemoryGame.ts`：

```ts
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
```

- [ ] **Step 4: 运行，确认通过**

```bash
cd mobile && npx jest constants/__tests__/MemoryGame-test.ts
```

预期：PASS，全部 9 个测试通过。

- [ ] **Step 5: 提交**

```bash
cd mobile && git add constants/MemoryGame.ts constants/__tests__/MemoryGame-test.ts
git commit -m "feat(game): 卡面素材库与档位常量

16 个图标名已逐个核对 MaterialCommunityIcons glyphmap，测试把这一点锁住：
猜一个不存在的名字不会报错，只会渲染成空白方块，在小卡片上肉眼极难发现。

档位文案的断言防的是设计意图被'顺手改清楚'——「简单/困难」会逼老人
对自己的认知能力做评估，是刻意避开的。"
```

---

### Task 3: useMemoryGame —— 发牌与初始状态

**Files:**
- Create: `mobile/hooks/useMemoryGame.ts`
- Create: `mobile/hooks/__tests__/useMemoryGame-test.ts`

**Interfaces:**
- Consumes: Task 2 的 `CARD_FACES` / `DECK_SIZES` / `DeckSizeKey`
- Produces:
  - `type Card = { key: string; faceId: string; matched: boolean }`
  - `type GameStatus = 'playing' | 'complete'`
  - `function buildDeck(deckSize: DeckSizeKey): Card[]`
  - `function useMemoryGame(deckSize: DeckSizeKey): { cards: Card[]; status: GameStatus; isFlipped: (key: string) => boolean; flip: (key: string) => void; restart: () => void }`

本任务只实现发牌与初始状态；`flip` 先留空实现，Task 4 填。

- [ ] **Step 1: 写失败的测试**

创建 `mobile/hooks/__tests__/useMemoryGame-test.ts`：

```ts
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
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd mobile && npx jest hooks/__tests__/useMemoryGame-test.ts
```

预期：FAIL —— `Cannot find module '@/hooks/useMemoryGame'`。

- [ ] **Step 3: 写实现**

创建 `mobile/hooks/useMemoryGame.ts`：

```ts
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

  // Task 4 填充
  const flip = useCallback((_key: string) => {}, []);

  return { cards, status, isFlipped, flip, restart };
}
```

- [ ] **Step 4: 运行，确认通过**

```bash
cd mobile && npx jest hooks/__tests__/useMemoryGame-test.ts
```

预期：PASS，12 个测试通过（3 档 × 3 项 + 初始状态 3 项）。

- [ ] **Step 5: 提交**

```bash
cd mobile && git add hooks/useMemoryGame.ts hooks/__tests__/useMemoryGame-test.ts
git commit -m "feat(game): useMemoryGame 发牌与初始状态

洗牌用 Fisher-Yates，测试断言的是不变量（每种图案恰好两张、key 唯一、
总数等于档位），与洗牌顺序无关，所以不需要注入假随机源。"
```

---

### Task 4: useMemoryGame —— 翻牌、配对判定、完成态

**Files:**
- Modify: `mobile/hooks/useMemoryGame.ts`（替换 Task 3 留空的 `flip`）
- Modify: `mobile/hooks/__tests__/useMemoryGame-test.ts`（追加 describe 块）

**Interfaces:**
- Consumes: Task 3 的 `useMemoryGame` / `Card` / `GameStatus`
- Produces: 可用的 `flip(key)`；配对成功的牌 `matched` 置 true 并永久正面朝上

- [ ] **Step 1: 写失败的测试**

先改 `mobile/hooks/__tests__/useMemoryGame-test.ts` 顶部的两行 import（`act` 与 `Card` 都是本任务新用到的，**import 必须留在文件顶部**，不要跟着下面的追加块走到末尾去）：

```ts
import { act, renderHook } from '@testing-library/react-native';
import { useMemoryGame, type Card } from '@/hooks/useMemoryGame';
```

然后在文件末尾追加：

```ts
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
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd mobile && npx jest hooks/__tests__/useMemoryGame-test.ts
```

预期：FAIL —— 「翻开一张牌后它正面朝上」等用例失败，因为 `flip` 还是空实现。

- [ ] **Step 3: 写实现**

在 `mobile/hooks/useMemoryGame.ts` 中，把 Task 3 留下的这一行删掉：

```ts
  // Task 4 填充
  const flip = useCallback((_key: string) => {}, []);
```

替换为：

```ts
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
```

- [ ] **Step 4: 运行，确认通过**

```bash
cd mobile && npx jest hooks/__tests__/useMemoryGame-test.ts
```

预期：PASS，全部通过（Task 3 的 12 个 + 本任务的 8 个）。

- [ ] **Step 5: 提交**

```bash
cd mobile && git add hooks/useMemoryGame.ts hooks/__tests__/useMemoryGame-test.ts
git commit -m "feat(game): 翻牌、配对判定、完成态

配对成功的牌不从牌堆移除，靠 matched 保持正面朝上——移除会导致布局
跳动，老人会丢失赖以定位的空间记忆锚点。

测试用 findPair/findMismatch 按 faceId 现找而不是写死下标，因为洗牌
是随机的。"
```

---

### Task 5: useMemoryGame —— 错配停留、判定期锁定、换档位重开

这是状态机最容易写错、也最难用肉眼发现问题的一段。三条行为都有明确的适老理由（见 spec §6.2）。

**Files:**
- Modify: `mobile/hooks/useMemoryGame.ts`
- Modify: `mobile/hooks/__tests__/useMemoryGame-test.ts`

**Interfaces:**
- Consumes: Task 4 的 `flip`
- Produces: 完整的 `useMemoryGame`，供 Task 9 组装使用（对外签名不变）

- [ ] **Step 1: 写失败的测试**

在测试文件的 import 里补上 `MISMATCH_HOLD_MS`：

```ts
import { DECK_SIZES, MISMATCH_HOLD_MS, type DeckSizeKey } from '@/constants/MemoryGame';
```

在文件末尾追加：

```ts
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
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd mobile && npx jest hooks/__tests__/useMemoryGame-test.ts
```

预期：FAIL —— 错配的牌永远不翻回（Task 4 的实现里那个分支是空的），且换档位不重开。

- [ ] **Step 3: 写实现**

`mobile/hooks/useMemoryGame.ts` 完整替换为：

```ts
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  CARD_FACES,
  DECK_SIZES,
  MISMATCH_HOLD_MS,
  type DeckSizeKey,
} from '@/constants/MemoryGame';

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
  /** 错配停留期。这期间忽略一切点击，否则手抖连点会让第三张牌覆盖 flipped。 */
  const [locked, setLocked] = useState(false);
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearHoldTimer = useCallback(() => {
    if (holdTimer.current !== null) {
      clearTimeout(holdTimer.current);
      holdTimer.current = null;
    }
  }, []);

  const restart = useCallback(() => {
    clearHoldTimer();
    setCards(buildDeck(deckSize));
    setFlipped([]);
    setLocked(false);
  }, [clearHoldTimer, deckSize]);

  // 换档位 = 用新牌数重开一局。跳过首次运行，否则会把 useState 初始化时
  // 发的那副牌立刻丢掉重发一次（多一次无谓渲染）。
  const isFirstRun = useRef(true);
  useEffect(() => {
    if (isFirstRun.current) {
      isFirstRun.current = false;
      return;
    }
    restart();
  }, [deckSize, restart]);

  // 卸载时清掉挂起的定时器，避免在已销毁的组件上 setState
  useEffect(() => clearHoldTimer, [clearHoldTimer]);

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

  const flip = useCallback(
    (key: string) => {
      if (locked) return;
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
        return;
      }

      // 翻错了。没有任何惩罚，只是让他把第二张牌看清楚再翻回去。
      setLocked(true);
      holdTimer.current = setTimeout(() => {
        setFlipped([]);
        setLocked(false);
        holdTimer.current = null;
      }, MISMATCH_HOLD_MS);
    },
    [cards, flipped, locked],
  );

  return { cards, status, isFlipped, flip, restart };
}
```

- [ ] **Step 4: 运行，确认全部通过**

```bash
cd mobile && npm test
```

预期：PASS。`useMemoryGame-test.ts` 共 27 个测试，加上 Task 1 的 2 个、Task 2 的 9 个。

- [ ] **Step 5: 提交**

```bash
cd mobile && git add hooks/useMemoryGame.ts hooks/__tests__/useMemoryGame-test.ts
git commit -m "feat(game): 错配停留、判定期锁定、换档位重开

三条都有适老理由：1200ms 停留是因为老人反应慢，翻回太快他没看清第二张
牌这一轮就白给了；判定期锁定是因为手抖连点会让第三张牌覆盖 flipped，
状态机错乱；换档位重开跳过首次运行，避免把初始化发的牌立刻丢掉重发。

状态机到此完整，UI 只是它的投影。"
```

---

> **Task 6 起是 UI 层。** spec §10.2 明确只测纯逻辑 hook、不测 UI 组件，所以下面四个任务
> 没有自动化测试，改用**具体的人工验收步骤**。每条验收都写明了"看什么"，不要用
> "看起来正常"这种验收标准。
>
> 启动预览：`cd mobile && npx expo start --web`，浏览器开 `http://localhost:8081`，
> 切到「练练脑」tab。

### Task 6: MemoryCard 组件

**Files:**
- Create: `mobile/components/game/MemoryCard.tsx`

**Interfaces:**
- Consumes: Task 2 的 `CardFace`；`constants/Design.ts` 的 `Design`
- Produces:
  - `const CARD_MIN_SIZE = 64`
  - `const CARD_WORD_MIN_SIZE = 92`
  - 默认导出 `MemoryCard`，props：`{ face: CardFace; faceUp: boolean; matched: boolean; size: number; onPress: () => void }`

- [ ] **Step 1: 写组件**

创建 `mobile/components/game/MemoryCard.tsx`：

```tsx
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import { Design } from '@/constants/Design';
import type { CardFace } from '@/constants/MemoryGame';

/** 点击区下限。通用无障碍标准是 44，这里翻倍——目标用户手抖。 */
export const CARD_MIN_SIZE = 64;

/** 小于这个尺寸就不显示中文词：挤成一团的字比没有字更难认。 */
export const CARD_WORD_MIN_SIZE = 92;

type Props = {
  face: CardFace;
  faceUp: boolean;
  matched: boolean;
  size: number;
  onPress: () => void;
};

export default function MemoryCard({ face, faceUp, matched, size, onPress }: Props) {
  const iconSize = Math.round(size * (size >= CARD_WORD_MIN_SIZE ? 0.4 : 0.52));
  const showWord = size >= CARD_WORD_MIN_SIZE;

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ disabled: matched }}
      accessibilityLabel={faceUp ? face.zh : '还没翻开的牌'}
      style={[
        styles.card,
        { width: size, height: size },
        faceUp ? (matched ? styles.matched : styles.faceUp) : styles.faceDown,
      ]}
    >
      {faceUp ? (
        <View style={styles.content}>
          <MaterialCommunityIcons
            name={face.icon}
            size={iconSize}
            color={Design.colors.onPrimaryContainer}
          />
          {showWord ? (
            <Text style={styles.word} numberOfLines={1}>
              {face.zh}
            </Text>
          ) : null}
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    minWidth: CARD_MIN_SIZE,
    minHeight: CARD_MIN_SIZE,
    borderRadius: Design.layout.radiusSmall,
    alignItems: 'center',
    justifyContent: 'center',
  },
  content: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  // 背面：素净的暖色块，不画花纹——花纹会被误认成图案
  faceDown: {
    backgroundColor: Design.colors.surfaceDim,
    borderWidth: 1,
    borderColor: Design.colors.outline,
  },
  faceUp: {
    backgroundColor: Design.colors.surface,
    borderWidth: 1,
    borderColor: Design.colors.outline,
  },
  // 配对成功：底色变暖，这是全局唯一的正向反馈。没有对应的负向反馈。
  matched: {
    backgroundColor: Design.colors.primaryContainer,
    borderWidth: 1,
    borderColor: Design.colors.primaryContainer,
  },
  word: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 14,
    color: Design.colors.text.secondary,
  },
});
```

- [ ] **Step 2: 人工验收**

组件还没被任何页面引用，本步只验证它能通过类型检查：

```bash
cd mobile && npx tsc --noEmit
```

预期：无错误输出。若报 `face.icon` 类型不兼容，说明 Task 2 的 `IconName` 类型没导出好，回头检查。

- [ ] **Step 3: 提交**

```bash
cd mobile && git add components/game/MemoryCard.tsx
git commit -m "feat(game): MemoryCard 单卡组件

点击区下限 64（通用标准 44 的翻倍），目标用户手抖。
小于 92px 时不显示中文词——挤成一团的字比没有字更难认。
配对成功变底色是全局唯一的正向反馈，没有对应的负向反馈。"
```

---

### Task 7: CardGrid 组件

**Files:**
- Create: `mobile/components/game/CardGrid.tsx`

**Interfaces:**
- Consumes: Task 6 的 `MemoryCard` / `CARD_MIN_SIZE`；Task 3 的 `Card`；Task 2 的 `CARD_FACES`
- Produces: 默认导出 `CardGrid`，props：`{ cards: Card[]; columns: number; isFlipped: (key: string) => boolean; onFlip: (key: string) => void }`

- [ ] **Step 1: 写组件**

创建 `mobile/components/game/CardGrid.tsx`：

```tsx
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
    const available = Math.min(width, MAX_GRID_WIDTH) - Design.layout.spacing * 2;
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
```

- [ ] **Step 2: 类型检查**

```bash
cd mobile && npx tsc --noEmit
```

预期：无错误输出。

- [ ] **Step 3: 提交**

```bash
cd mobile && git add components/game/CardGrid.tsx
git commit -m "feat(game): CardGrid 网格布局

卡片尺寸按可用宽度和列数算，下限锁在 CARD_MIN_SIZE。网格最大宽度 560：
平板/桌面上不让牌摊满屏，扫视距离太长反而更难记。"
```

---

### Task 8: DeckSizePicker 与 RoundComplete 组件

两个都是小的展示型组件，一起做一起审。

**Files:**
- Create: `mobile/components/game/DeckSizePicker.tsx`
- Create: `mobile/components/game/RoundComplete.tsx`

**Interfaces:**
- Consumes: Task 2 的 `DECK_SIZES` / `DeckSizeKey`
- Produces:
  - 默认导出 `DeckSizePicker`，props：`{ value: DeckSizeKey; onChange: (key: DeckSizeKey) => void }`
  - 默认导出 `RoundComplete`，props：`{ onRestart: () => void }`

- [ ] **Step 1: 写 DeckSizePicker**

创建 `mobile/components/game/DeckSizePicker.tsx`：

```tsx
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
    gap: 10,
    justifyContent: 'center',
    flexWrap: 'wrap',
  },
  option: {
    minHeight: 64, // 与卡片同一个手抖容错标准
    paddingHorizontal: 20,
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
    fontSize: 18,
  },
  labelIdle: { color: Design.colors.text.secondary },
  labelActive: { color: Design.colors.onPrimaryContainer },
});
```

- [ ] **Step 2: 写 RoundComplete**

创建 `mobile/components/game/RoundComplete.tsx`：

```tsx
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
```

- [ ] **Step 3: 类型检查**

```bash
cd mobile && npx tsc --noEmit
```

预期：无错误输出。

- [ ] **Step 4: 提交**

```bash
cd mobile && git add components/game/DeckSizePicker.tsx components/game/RoundComplete.tsx
git commit -m "feat(game): 档位选择器与收尾组件

档位选择器常驻屏幕下方，不是进入前的选择界面——让老人每次先做一道
选择题是额外认知负担。

收尾语不含任何成绩信息：没有用时、没有翻牌次数。报数字就是在评判他。"
```

---

### Task 9: two.tsx 组装与档位持久化

最后一步：把前面所有东西接起来，替换掉 Expo 默认模板。

**Files:**
- Modify: `mobile/app/(tabs)/two.tsx`（整体替换）

**Interfaces:**
- Consumes: Task 2 的 `DECK_SIZES` / `DEFAULT_DECK_SIZE` / `DECK_SIZE_STORAGE_KEY` / `isDeckSizeKey`；Task 5 的 `useMemoryGame`；Task 7 的 `CardGrid`；Task 8 的 `DeckSizePicker` / `RoundComplete`
- Produces: 完整可玩的「练练脑」屏幕

- [ ] **Step 1: 整体替换 two.tsx**

把 `mobile/app/(tabs)/two.tsx` 的全部内容替换为：

```tsx
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
```

- [ ] **Step 2: 类型检查 + 跑全部测试**

```bash
cd mobile && npx tsc --noEmit && npm test
```

预期：类型检查无输出，测试全绿。

- [ ] **Step 3: 人工验收**

```bash
cd mobile && npx expo start --web
```

浏览器开 `http://localhost:8081`，切到「练练脑」tab，**逐条**核对：

1. **默认发 12 张牌，3 列 4 行**，全部背面朝上（素净暖色块，无花纹）。
2. **点一张** → 翻开，显示图标 + 中文词。
3. **点两张不同的** → 两张都保持正面 **约 1.2 秒**，然后一起翻回。期间点第三张**没有任何反应**。
4. **点两张相同的** → 两张底色变暖（`primaryContainer`），**保持正面不翻回、不消失**，布局不跳动。
5. **配错时**：不变红、不震动、无提示音、屏幕上没有任何数字。
6. **全部配对完** → 出现一句夸奖 + 「再来一局」按钮，**画面上没有用时、没有翻牌次数**。
7. **点「再来一局」** → 重新发牌，全部背面朝上。
8. **点「牌多一点」** → 变成 16 张 4 列，重新发牌。**卡片上的中文词仍然读得清**（若挤成一团，说明 `CARD_WORD_MIN_SIZE` 阈值需要调高，见开放项）。
9. **点「牌少一点」** → 变成 6 张 2 列。
10. **刷新页面** → 档位保持上次选的那一档，不回到「正好」。
11. **窗口缩到手机宽度**（浏览器开发者工具切 375px）→ 牌不溢出、不横向滚动。

任何一条不符，先停下来修，不要带着问题往下走。

- [ ] **Step 4: 提交**

```bash
cd mobile && git add "app/(tabs)/two.tsx"
git commit -m "feat(game): 练练脑屏幕组装，替换 Expo 默认模板

档位从 AsyncStorage 读，读完再渲染牌桌，免得先闪一副默认档位的牌。
存储读写失败一律静默降级到默认档位——这个游戏不该因为存储问题打不开。

牌桌单独成组件是因为 useMemoryGame 需要非 null 的 deckSize，
而 hook 不能写在条件分支里。"
```

---

## 自审结论

写完后对照 spec 逐节核过，记录如下。

### Spec 覆盖

| Spec 小节 | 对应任务 |
|---|---|
| §5 文件结构 | Task 2/3/6/7/8/9 逐个创建 |
| §5.1 hook 零 RN 依赖 | Task 3/5（`useMemoryGame.ts` 只 import react 与 constants） |
| §6 状态机（无 idle、直接发牌） | Task 9（读存储后直接进 GameBoard，无选择门） |
| §6.1 翻牌转移表 | Task 4（前 3 行 + 已配对/重复点击）、Task 5（错配停留、判定期锁定） |
| §6.2 三个适老细节 | Task 5 实现 + 注释；Task 4 注释「不移除」 |
| §6.3 完成条件 | Task 4「完成态」describe |
| §7 档位与布局 | Task 2 `DECK_SIZES`；Task 9 持久化 |
| §8 素材库 | Task 2（16 项，图标名已核对） |
| §9 反馈与无障碍 | Task 6（点击区、accessibilityLabel）、Task 8（无成绩信息） |
| §10.2 五项必测 | Task 3（第 1 项）、Task 4（第 2、4 项）、Task 5（第 3、5 项） |

无缺口。

### 修正记录

自审时发现并已在上文修掉的三处：

1. **Task 6 的 `showWord` 阈值原本写死在 JSX 里**，改成具名导出 `CARD_WORD_MIN_SIZE`——spec §11.1 把「大档文字读不清」列为待真机验证的开放项，验证后要调的就是这个值，埋成魔数会很难找。
2. **Task 9 原本在读 AsyncStorage 时渲染 loading spinner**，改成渲染空 View。读存储通常几毫秒，一闪而过的转圈比空白更烦人。
3. **Task 5 的 `useEffect` 原本没有跳过首次运行**，会把 `useState` 初始化时发的那副牌立刻丢掉重发一次。加了 `isFirstRun` ref，并补了「档位没变时不重新发牌」的测试把它锁住。
4. **Task 4 的 `import type { Card }` 原本混在「文件末尾追加」的代码块里**，照做会得到一个位于文件底部的 import。已改为并入 Step 1 的顶部 import 编辑。

### 已知的中间态（不是缺陷）

Task 4 结束时，翻错两张牌后 `flipped` 不会被清空（错配分支是空的），此时再点第三张会拿前两张重复比较一次。Task 4 的测试不触及这条路径，Task 5 补上错配分支后即消失。这是 TDD 的正常中间态——**Task 4 单独跑测试是绿的，但那一版不要拿去手动试玩**。

### 类型一致性

`Card` / `GameStatus` / `DeckSizeKey` / `CardFace` / `IconName` 在 Task 2→3→5→6→7→9 之间的引用已逐个核对，签名一致。`isFlipped` / `flip` / `restart` 三个方法名在 hook 定义处与全部四个消费点拼写一致。

### 遗留的开放项（来自 spec §11，实现后处理）

1. **大档卡片尺寸**：16 张时单卡约 85px，`CARD_WORD_MIN_SIZE = 92` 意味着**大档默认不显示中文词**。Task 9 验收第 8 条会暴露这一点。真机核对后二选一：调低阈值让词显示，或接受大档只有图标。
2. **`MISMATCH_HOLD_MS = 1200`**：需真实老人测试后调整。
3. **图标年代感**：真正的粮票、搪瓷缸子、二八大杠图标库里没有，v1 接受「通用老物件」的妥协。
