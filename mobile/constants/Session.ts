import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * 会话身份
 *
 * elder_id：标识「这位老人」，跨会话持久 —— 长程记忆（事实台账）按它归档，
 *           所以它必须在多次对话之间保持稳定。同一台设备每次启动都要读到
 *           同一个 elder_id，否则多台设备打包出来的 App 会全部退到固定值，
 *           记忆互相串。
 * session_id：标识「这一次对话」，每次开始对话重新生成 —— 对话历史、策略延续、
 *            类别延续这些会话级状态按它隔离，上一次对话的状态不应残留到下一次。
 *
 * Web 端用 localStorage（同步），原生端用 AsyncStorage（异步，App 打包后靠它
 * 持久化，否则每次冷启动都会退到 FALLBACK_ELDER_ID，多设备共享同一份记忆）。
 */

const ELDER_ID_KEY = 'agetalker.elder_id';
const FALLBACK_ELDER_ID = 'elder_default';

const randomSuffix = (): string => Math.random().toString(36).slice(2, 10);

export const getElderId = async (): Promise<string> => {
  if (Platform.OS === 'web') {
    try {
      const existing = window.localStorage.getItem(ELDER_ID_KEY);
      if (existing) return existing;
      const created = `elder_${randomSuffix()}`;
      window.localStorage.setItem(ELDER_ID_KEY, created);
      return created;
    } catch {
      // 隐私模式下 localStorage 不可用：本次会话内仍唯一，但刷新页面会变
      return `elder_${randomSuffix()}`;
    }
  }

  try {
    const existing = await AsyncStorage.getItem(ELDER_ID_KEY);
    if (existing) return existing;
    const created = `elder_${randomSuffix()}`;
    await AsyncStorage.setItem(ELDER_ID_KEY, created);
    return created;
  } catch {
    // AsyncStorage 异常（极少见）：退回固定值，至少不崩，但记忆会跨设备共享
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

/**
 * 默认主动招呼的时间点（小时，本地时间）。
 *
 * 画像采到 daily_routine 之前用这张表。注意服务端还有一道夜间静默硬边界
 * （21:00-07:00），这张表改错了也不会半夜出声。
 */
export const PROACTIVE_SCHEDULE = [9, 14, 19];

/** 主动招呼说完后，开麦等多久算没人应答（毫秒）。后端同名参数是 20 秒。 */
export const PROACTIVE_NO_ANSWER_MS = 20000;

/**
 * 等主动招呼的语音放完，最多等多久（毫秒）。
 *
 * 纯兜底：TTS 请求挂死时播放标志永远不会翻回 false，不能就这么无限等下去，
 * 否则这一轮招呼再也不会开麦。正常一段招呼的语音在 20 秒以内。
 */
export const PROACTIVE_PLAYBACK_WAIT_MAX_MS = 60000;
