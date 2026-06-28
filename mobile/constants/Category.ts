/**
 * Psychological Category Display Constants
 *
 * Maps backend psychological category keys (from the DeepSeek router LLM)
 * to Chinese display names for the frontend UI.
 *
 * Categories are delivered via the SSE done event and surfaced in transcript
 * bubbles alongside the acoustic emotion label from emotion2vec.
 *
 * NOTE: 'crisis' is NOT in the backend CATEGORY_STRATEGY_MAP — it is a
 * hard circuit-breaker path (build_crisis_prompt).  We include it here so
 * the frontend can display it when the router detects high risk.
 */
export const CATEGORY_ZH_MAP: Record<string, string> = {
  depression: '抑郁',
  anxiety:    '焦虑',
  anger:      '愤怒',
  loneliness: '孤独',
  grief:      '哀伤',
  positive:   '积极',
  neutral:    '中性/闲聊',
  crisis:     '高危',
};
