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
