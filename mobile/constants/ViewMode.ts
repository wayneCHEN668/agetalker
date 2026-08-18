import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * 聊天页展示模式
 *
 * 'orb'  — 抽象可视化（多层同心点阵），默认模式，老人第一次进来看到的是圆而不是字
 * 'chat' — 传统对话窗口，保留给需要回看文字/情绪标签的场景
 *
 * 持久化方式照抄 Session.ts 的 elder_id：web 用 localStorage（同步），
 * 原生端用 AsyncStorage（异步）。跨会话记住上次选的模式。
 */

export type ViewMode = 'orb' | 'chat';

const VIEW_MODE_KEY = 'agetalker.view_mode';
export const DEFAULT_VIEW_MODE: ViewMode = 'orb';

const isValidMode = (v: string | null): v is ViewMode => v === 'orb' || v === 'chat';

export const getViewMode = async (): Promise<ViewMode> => {
  if (Platform.OS === 'web') {
    try {
      const existing = window.localStorage.getItem(VIEW_MODE_KEY);
      return isValidMode(existing) ? existing : DEFAULT_VIEW_MODE;
    } catch {
      return DEFAULT_VIEW_MODE;
    }
  }

  try {
    const existing = await AsyncStorage.getItem(VIEW_MODE_KEY);
    return isValidMode(existing) ? existing : DEFAULT_VIEW_MODE;
  } catch {
    return DEFAULT_VIEW_MODE;
  }
};

export const setViewMode = async (mode: ViewMode): Promise<void> => {
  if (Platform.OS === 'web') {
    try {
      window.localStorage.setItem(VIEW_MODE_KEY, mode);
    } catch {
      // 隐私模式下 localStorage 不可用：本次会话内仍生效，只是刷新后会退回默认值
    }
    return;
  }

  try {
    await AsyncStorage.setItem(VIEW_MODE_KEY, mode);
  } catch {
    // 忽略：至多下次冷启动退回默认模式，不影响当前会话
  }
};
