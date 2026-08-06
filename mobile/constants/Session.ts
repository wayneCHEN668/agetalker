/**
 * 会话身份
 *
 * elder_id：标识「这位老人」，跨会话持久 —— 长程记忆（事实台账）按它归档，
 *           所以它必须在多次对话之间保持稳定。
 * session_id：标识「这一次对话」，每次开始对话重新生成 —— 对话历史、策略延续、
 *            类别延续这些会话级状态按它隔离，上一次对话的状态不应残留到下一次。
 *
 * 目前是单用户 demo 形态，elder_id 存在浏览器 localStorage 里即可。原生端没有
 * localStorage，退回固定值 —— 这样不必为一个 demo 形态的需求引入 AsyncStorage 依赖。
 */

const ELDER_ID_KEY = 'agetalker.elder_id';
const FALLBACK_ELDER_ID = 'elder_default';

const randomSuffix = (): string => Math.random().toString(36).slice(2, 10);

export const getElderId = (): string => {
  try {
    const existing = window.localStorage.getItem(ELDER_ID_KEY);
    if (existing) return existing;
    const created = `elder_${randomSuffix()}`;
    window.localStorage.setItem(ELDER_ID_KEY, created);
    return created;
  } catch {
    // 原生端 / 隐私模式下 localStorage 不可用
    return FALLBACK_ELDER_ID;
  }
};

export const newSessionId = (): string =>
  `s_${Date.now().toString(36)}_${randomSuffix()}`;
