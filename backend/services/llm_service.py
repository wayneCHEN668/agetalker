# e:\MyDoc\APP\agetalker\backend\services\llm_service.py

import logging
from typing import Generator
from openai import OpenAI
from config import (
    DASHSCOPE_API_KEY,
    QWEN_BASE_URL,
    QWEN_MODEL,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_TOP_P,
    LLM_MAX_HISTORY_TURNS,
    CRISIS_KEYWORDS,
    TTS_PARAMS_MAP,
)
from prompts.templates import build_normal_prompt, build_crisis_prompt

logger = logging.getLogger(__name__)


class LLMService:
    """
    通义千问 LLM 心理回复服务。
    支持多会话隔离。
    """

    def __init__(self):
        self.client = OpenAI(
            api_key  = DASHSCOPE_API_KEY,
            base_url = QWEN_BASE_URL,
        )
        # 对话历史：{session_id: [{'role': 'user'|'assistant', 'content': str}, ...]}
        self.sessions: dict[str, list[dict]] = {}
        logger.info("LLM 服务初始化完成 ✅")


    def stream_reply(
        self,
        user_text: str,
        emotion:   dict,
        session_id: str = 'default'
    ) -> Generator[dict, None, None]:
        """
        流式生成心理回复。

        Args:
            user_text: STEP 1 转录文本
            emotion:   STEP 2 情绪结果字典
            session_id: 会话 ID

        Yields:
            {'type': 'delta',  'text': str,       'crisis': bool}
            {'type': 'done',   'full_text': str,   'crisis': bool,
             'emotion_label': str, 'tts_params': dict}
            {'type': 'error',  'message': str}
        """

        # ── 步骤 1：危机检测 ────────────────────────────────────────────────
        crisis = self._check_crisis(user_text)
        if crisis:
            logger.warning(f"⚠️  危机信号触发 | Session: {session_id} | 文本: {user_text[:50]}")

        # ── 步骤 2：获取会话历史 ───────────────────────────────────────────
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        
        conversation = self.sessions[session_id]

        # ── 步骤 3：构建 System Prompt ──────────────────────────────────────
        system_prompt = (
            build_crisis_prompt()       if crisis
            else build_normal_prompt(emotion)
        )

        # ── 步骤 4：追加用户消息到历史 ──────────────────────────────────────
        conversation.append({'role': 'user', 'content': user_text})

        # ── 步骤 5：裁剪历史，保留最近 N 轮 ────────────────────────────────
        max_msgs = LLM_MAX_HISTORY_TURNS * 2
        if len(conversation) > max_msgs:
            self.sessions[session_id] = conversation[-max_msgs:]
            conversation = self.sessions[session_id]

        # ── 步骤 6：组装完整消息列表 ────────────────────────────────────────
        messages = [
            {'role': 'system', 'content': system_prompt},
            *conversation,
        ]

        # ── 步骤 7：调用 Qwen API 流式生成 ──────────────────────────────────
        try:
            stream = self.client.chat.completions.create(
                model       = QWEN_MODEL,
                messages    = messages,
                stream      = True,
                max_tokens  = LLM_MAX_TOKENS,
                temperature = LLM_TEMPERATURE,
                top_p       = LLM_TOP_P,
            )
        except Exception as e:
            logger.error(f"Qwen API 调用失败 (Session: {session_id}): {e}", exc_info=True)
            yield {'type': 'error', 'message': str(e)}
            return

        # ── 步骤 8：流式处理输出 ─────────────────────────────────────────────
        full_reply = ''
        for chunk in stream:
            delta_text = chunk.choices[0].delta.content or ''
            if delta_text:
                full_reply += delta_text
                yield {
                    'type':   'delta',
                    'text':   delta_text,
                    'crisis': crisis,
                }

        # ── 步骤 9：保存助手回复到历史 ──────────────────────────────────────
        if full_reply:
            conversation.append(
                {'role': 'assistant', 'content': full_reply}
            )

        # ── 步骤 10：生成完毕信号 ─────────────────────────────────────────────
        yield {
            'type':          'done',
            'full_text':     full_reply,
            'crisis':        crisis,
            'emotion_label': emotion.get('label', 'neutral'),
            'tts_params':    self._get_tts_params(emotion, crisis),
        }


    def _check_crisis(self, text: str) -> bool:
        """检测用户文本是否包含危机信号关键词。"""
        return any(kw in text for kw in CRISIS_KEYWORDS)

    def _get_tts_params(self, emotion: dict, crisis: bool) -> dict:
        """根据情绪和是否危机返回 TTS 参数。"""
        if crisis:
            return TTS_PARAMS_MAP['_crisis']
        label = emotion.get('label', 'neutral')
        return TTS_PARAMS_MAP.get(label, TTS_PARAMS_MAP['neutral'])

    def reset(self, session_id: str = 'default'):
        """重置指定会话的对话历史。"""
        if session_id in self.sessions:
            self.sessions[session_id].clear()
            logger.info(f"会话 {session_id} 历史已重置")
        else:
            logger.info(f"会话 {session_id} 不存在，无需重置")

    def get_history_turns(self, session_id: str = 'default') -> int:
        """获取指定会话的对话轮数。"""
        conversation = self.sessions.get(session_id, [])
        return len(conversation) // 2
