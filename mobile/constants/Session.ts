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

/**
 * 老人静默多久之后 AI 先开口（毫秒）。
 *
 * 远长于 ASR 的 1.5 秒断句阈值——那个判断的是"这句话说完了没有"，
 * 这个判断的是"他是不是不想说了"。量级估计，需要实机调；调错方向时
 * 宁可往长了调：对老人而言，被打断的代价远大于多等一会儿。
 *
 * 后端 config.SILENCE_PROMPT_SEC 是同一个值，两边都要改。
 */
export const SILENCE_PROMPT_MS = 25000;
