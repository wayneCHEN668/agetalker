import json
import logging
from typing import AsyncGenerator
from datetime import datetime, timezone, timedelta
from pathlib import Path
from openai import AsyncOpenAI
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
    CATEGORY_TTS_PARAMS_MAP,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    ROUTER_TEMPERATURE,
    ROUTER_MAX_TOKENS,
    ROUTER_CONTEXT_TURNS,
)
from prompts.templates import (
    build_normal_prompt,
    build_crisis_prompt,
    ROUTER_SYSTEM_PROMPT,
    build_router_user_prompt,
    resolve_strategy_id,
    CATEGORY_STRATEGY_MAP,
)

logger = logging.getLogger(__name__)

# 每个会话、每个类别最多保留多少条"已用策略"记录。只是为了不让长会话里这个列表
# 无限增长、拖累路由 prompt 的 token 量，不是业务上的限制。
_MAX_STRATEGY_HISTORY_PER_CATEGORY = 8


class LLMService:
    """
    通义千问 LLM 心理回复服务（v4：策略在多轮间延续）。

    支持多会话隔离 + 独立心理类别路由模型 + 会话级策略延续状态。

    v3 -> v4 变更：
    - 新增 self.strategy_history：{session_id: {category: [已用 strategy_id, ...]}}，
      会话级状态，与 self.sessions（对话历史）平级维护。
    - _route_category() 现在除了 category/matched_signals，还会解析并返回
      strategy_id（路由模型在同一次调用里，结合"已用过的策略"和当前这句话的
      内容，一并选出来）。这不增加任何新的网络往返——路由调用本来就要发生，
      只是这次调用的输入（策略库 + 已用历史）和输出（多一个 strategy_id 字段）
      更丰富了。
    - 解决的问题：以前生成 LLM 每轮都从完整策略菜单里自己挑，没有状态、没有
      记忆，容易在多轮对话里重复或跳跃。现在策略选择是路由那次调用基于会话
      历史做的显式决策，生成 LLM 只负责把指定的那一条自然地说出来。
    - 记录到 strategy_history 里的，是 resolve_strategy_id() 兜底之后真正会被
      注入到 system prompt 里的 id，不是路由模型原始返回的、可能无效的值——
      这样"已用策略"的记录才是可信的，不会出现追踪失真。
    """

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key  = DASHSCOPE_API_KEY,
            base_url = QWEN_BASE_URL,
        )
        # 路由专用客户端：指向 DeepSeek，与主生成客户端（self.client，Qwen）完全独立。
        self.router_client = AsyncOpenAI(
            api_key  = DEEPSEEK_API_KEY,
            base_url = DEEPSEEK_BASE_URL,
        )
        # 对话历史：{session_id: [{'role': 'user'|'assistant', 'content': str}, ...]}
        self.sessions: dict[str, list[dict]] = {}
        # 策略延续状态：{session_id: {category: [已用 strategy_id, ...]}}
        self.strategy_history: dict[str, dict[str, list[str]]] = {}
        logger.info("LLM 服务初始化完成 ✅ (生成: Qwen/AsyncOpenAI | 路由: DeepSeek/AsyncOpenAI | 策略延续: 已启用)")

    # ─── 路由 LLM ───────────────────────────────────────────────────────────

    async def _route_category(
        self,
        user_text: str,
        context: str = "",
        used_strategies: str = "",
    ) -> tuple[str, str, str]:
        """
        调用独立的路由模型（DeepSeek），判断当前这句话的心理类别，并选出这一轮
        该用的具体策略 id。

        设计要点：
        - 独立客户端（self.router_client）+ 独立模型（DEEPSEEK_MODEL），与主生成
          调用（self.client / QWEN_MODEL）完全分离。
        - 低 temperature、小 max_tokens，压低延迟——分类任务要的是稳定，不是创造性。
        - 路由失败（网络异常、JSON 解析失败、返回空内容、category 不在已知集合内、
          strategy_id 不在该类别的策略列表内）一律降级，不中断对话。

        Args:
            user_text: 当前这句话。
            context: 最近几轮对话拼成的上下文（由 _build_router_context 构建）。
            used_strategies: 这个会话里各类别已用过的策略 id（由 _format_used_strategies
                构建），供路由模型参考"该不该推进到下一步"，不是必须避开的黑名单。

        Returns:
            (category, matched_signals, strategy_id)
            strategy_id 为空字符串时，表示路由没有给出有效策略（is_crisis、解析
            失败、或返回的 id 不在该类别策略列表内），下游会通过 resolve_strategy_id()
            兜底为该类别的第一条策略。
        """
        try:
            resp = await self.router_client.chat.completions.create(
                model       = DEEPSEEK_MODEL,
                messages    = [
                    {'role': 'system', 'content': ROUTER_SYSTEM_PROMPT},
                    {'role': 'user',   'content': build_router_user_prompt(
                        user_text, context, used_strategies
                    )},
                ],
                temperature = ROUTER_TEMPERATURE,
                max_tokens  = ROUTER_MAX_TOKENS,
                response_format = {'type': 'json_object'},
            )
            raw = resp.choices[0].message.content
            if not raw:
                logger.warning("路由调用返回空内容，降级为 neutral")
                return 'neutral', '', ''

            result = json.loads(raw.strip())
            category = result.get('category', 'neutral')
            is_crisis = result.get('is_crisis', False)
            matched_signals = result.get('matched_signals', '')
            strategy_id = result.get('strategy_id', '')

            if is_crisis or category == 'crisis':
                return 'crisis', matched_signals, ''

            if category not in CATEGORY_STRATEGY_MAP:
                logger.warning(f"路由模型返回未知类别 '{category}'，降级为 neutral")
                return 'neutral', matched_signals, ''

            valid_ids = {s['id'] for s in CATEGORY_STRATEGY_MAP[category]['strategies']}
            if strategy_id not in valid_ids:
                if strategy_id:
                    logger.warning(
                        f"路由模型返回的 strategy_id '{strategy_id}' "
                        f"不在 {category} 的策略列表内，交给下游兜底"
                    )
                strategy_id = ''

            logger.debug(
                f"路由结果: category={category}, strategy_id={strategy_id or '(待兜底)'}, "
                f"signals={matched_signals}"
            )
            return category, matched_signals, strategy_id

        except Exception as e:
            logger.error(f"路由调用失败: {e}，降级为 neutral")
            return 'neutral', '路由暂不可用', ''

    @staticmethod
    def _build_router_context(conversation: list[dict], turns: int) -> str:
        """
        从会话历史中截取最近 N 轮，拼成路由 prompt 用的上下文字符串。

        1 轮 = 1 条 user + 1 条 assistant。会话第一句话时 conversation 为空，
        返回空字符串——这是正常情况，不是异常。每条消息截断到 60 字以内，
        避免上下文过长拖慢路由调用。
        """
        if not conversation or turns <= 0:
            return ''
        recent = conversation[-(turns * 2):]
        lines = [
            f"{'老人' if msg['role'] == 'user' else '心伴'}：{msg['content'][:60]}"
            for msg in recent
        ]
        return '\n'.join(lines)

    def _format_used_strategies(self, session_id: str) -> str:
        """
        把这个会话各类别已用过的策略 id 拼成字符串，传给路由模型做参考。

        格式形如 "anger：[pause_breathe,pause_breathe,uncover_need]"，重复出现
        说明这条策略被连续用了多次，这是有意保留的信息（不去重），让路由模型
        能判断"这条策略已经反复用了，是不是该推进了"。
        """
        history = self.strategy_history.get(session_id)
        if not history:
            return ''
        parts = [f"{cat}：[{','.join(ids)}]" for cat, ids in history.items() if ids]
        return '；'.join(parts)

    def _record_strategy_use(self, session_id: str, category: str, strategy_id: str):
        """
        记录这一轮实际生效的策略 id（必须是 resolve_strategy_id() 兜底之后的值，
        不能是路由模型原始返回的、可能无效的值），供下一轮路由判断参考。
        """
        per_session = self.strategy_history.setdefault(session_id, {})
        used = per_session.setdefault(category, [])
        used.append(strategy_id)
        per_session[category] = used[-_MAX_STRATEGY_HISTORY_PER_CATEGORY:]

    # ─── 主入口：流式生成回复 ────────────────────────────────────────────────

    async def stream_reply(
        self,
        user_text: str,
        emotion:   dict,
        session_id: str = 'default'
    ) -> AsyncGenerator[dict, None]:
        """
        流式生成心理回复。

        流程：
            1. 获取/初始化会话历史（提前到最前面，路由调用需要从历史里取上下文）
            2. 关键词危机检测（硬性熔断层，不依赖任何 LLM 调用，永远最先生效）
            3. 若关键词层未命中：调用独立的路由模型（DeepSeek），结合最近几轮
               对话上下文 + 本会话各类别已用过的策略，判断心理类别并选出这一轮
               该用的具体策略 id；is_crisis 作为第二层语义熔断。
            4. 把路由选出的 strategy_id 兜底校验后记入会话状态，按危机/类别+策略
               构建 system prompt，调用 Qwen 主生成模型流式输出回复。

        Args:
            user_text: STEP 1 转录文本
            emotion:   STEP 2 情绪结果字典（仅用于语气措辞和 TTS 参数，不参与类别路由判断）
            session_id: 会话 ID

        Yields:
            {'type': 'delta',  'text': str,       'crisis': bool}
            {'type': 'done',   'full_text': str,   'crisis': bool,
             'emotion_label': str, 'category': str, 'strategy_id': str, 'tts_params': dict}
            {'type': 'error',  'message': str}
        """

        # ── 步骤 1：获取/初始化会话历史（提前，路由调用要用它取上下文）──────────
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        conversation = self.sessions[session_id]

        # ── 步骤 2：关键词危机检测（硬性熔断层，第一优先级，不依赖任何 LLM）────
        category = 'neutral'      # 默认值（危机被拦截、或路由失败兜底时使用）
        matched_signals = ''
        strategy_id = ''
        crisis = self._check_crisis(user_text)
        if crisis:
            logger.warning(f"⚠️  危机信号触发 (关键词) | Session: {session_id} | 文本: {user_text[:50]}")
            self._dispatch_crisis_event(user_text, session_id)

        # ── 步骤 3：路由模型判断心理类别 + 选策略（仅在关键词层未命中时才需要）──
        if not crisis:
            context = self._build_router_context(conversation, ROUTER_CONTEXT_TURNS)
            used_strategies = self._format_used_strategies(session_id)
            category, matched_signals, raw_strategy_id = await self._route_category(
                user_text, context, used_strategies
            )
            if category == 'crisis':
                crisis = True
                logger.warning(f"⚠️  危机信号触发 (路由 LLM) | Session: {session_id} | 文本: {user_text[:50]}")
                self._dispatch_crisis_event(user_text, session_id)
                matched_signals = ''
                strategy_id = ''
            else:
                # 兜底校验，记录的必须是这个最终生效的值，不是路由原始返回值
                strategy_id = resolve_strategy_id(category, raw_strategy_id)
                self._record_strategy_use(session_id, category, strategy_id)

        # ── 步骤 4：构建 System Prompt ──────────────────────────────────────
        if crisis:
            system_prompt = build_crisis_prompt()
        else:
            system_prompt = build_normal_prompt(category, emotion, matched_signals, strategy_id)

        # ── 步骤 5：追加用户消息到历史 ──────────────────────────────────────
        conversation.append({'role': 'user', 'content': user_text})

        # ── 步骤 6：裁剪历史，保留最近 N 轮 ────────────────────────────────
        max_msgs = LLM_MAX_HISTORY_TURNS * 2
        if len(conversation) > max_msgs:
            self.sessions[session_id] = conversation[-max_msgs:]
            conversation = self.sessions[session_id]

        # ── 步骤 7：组装完整消息列表 ────────────────────────────────────────
        messages = [
            {'role': 'system', 'content': system_prompt},
            *conversation,
        ]

        # ── 步骤 8：调用 Qwen API 流式生成 ──────────────────────────────────
        try:
            stream = await self.client.chat.completions.create(
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

        # ── 步骤 9：流式处理输出 ─────────────────────────────────────────────
        full_reply = ''
        async for chunk in stream:
            delta_text = chunk.choices[0].delta.content or ''
            if delta_text:
                full_reply += delta_text
                yield {
                    'type':   'delta',
                    'text':   delta_text,
                    'crisis': crisis,
                }

        # ── 步骤 10：保存助手回复到历史 ─────────────────────────────────────
        if full_reply:
            conversation.append(
                {'role': 'assistant', 'content': full_reply}
            )

        # ── 步骤 11：生成完毕信号 ─────────────────────────────────────────────
        yield {
            'type':         'done',
            'full_text':    full_reply,
            'crisis':       crisis,
            'category':     category if not crisis else 'crisis',
            'strategy_id':  strategy_id,
            'tts_params':   self._get_tts_params_by_category(category, crisis),
        }

    # ─── 危机检测 ───────────────────────────────────────────────────────────

    def _check_crisis(self, text: str) -> bool:
        """关键词匹配危机检测。零延迟，不依赖任何 LLM 调用。"""
        return any(kw in text for kw in CRISIS_KEYWORDS)

    def _dispatch_crisis_event(self, user_text: str, session_id: str):
        """
        危机事件分发。

        当前实现：结构化日志 + JSON 事件文件（供监控/通知服务轮询）。
        后续接入家庭沟通模块时，替换为 MQTT/Webhook/推送调用。
        """
        event = {
            'type':       'crisis_alert',
            'session_id': session_id,
            'user_text':  user_text[:100],
            'timestamp':  datetime.now(timezone(timedelta(hours=8))).isoformat(),
        }
        # 1. 结构化日志（供日志系统采集）
        logger.critical(f"CRISIS_EVENT: {json.dumps(event, ensure_ascii=False)}")
        # 2. 事件文件（供外部监控轮询，如护工端 App）
        try:
            events_dir = Path('data/crisis_events')
            events_dir.mkdir(parents=True, exist_ok=True)
            ts = event['timestamp'][:19].replace(':', '-')
            event_file = events_dir / f"{ts}_{session_id}.json"
            event_file.write_text(json.dumps(event, ensure_ascii=False, indent=2),
                                 encoding='utf-8')
            logger.info(f"危机事件已写入: {event_file}")
        except Exception as e:
            logger.error(f"写入危机事件文件失败: {e}")

    # ─── TTS 参数 ────────────────────────────────────────────────────────────

    def _get_tts_params(self, emotion: dict, crisis: bool) -> dict:
        """（保留）根据声学情绪返回 TTS 参数。"""
        if crisis:
            return TTS_PARAMS_MAP['_crisis']
        label = emotion.get('label', 'neutral')
        return TTS_PARAMS_MAP.get(label, TTS_PARAMS_MAP['neutral'])

    def _get_tts_params_by_category(self, category: str, crisis: bool) -> dict:
        """根据路由模型判定的心理类别返回 TTS 参数（语义驱动）。"""
        if crisis:
            return CATEGORY_TTS_PARAMS_MAP['crisis']
        return CATEGORY_TTS_PARAMS_MAP.get(category, CATEGORY_TTS_PARAMS_MAP['neutral'])

    # ─── 会话管理 ────────────────────────────────────────────────────────────

    def reset(self, session_id: str = 'default'):
        """重置指定会话的对话历史和策略延续状态。"""
        had_session = session_id in self.sessions
        if had_session:
            self.sessions[session_id].clear()
        self.strategy_history.pop(session_id, None)
        if had_session:
            logger.info(f"会话 {session_id} 历史与策略状态已重置")
        else:
            logger.info(f"会话 {session_id} 不存在，无需重置")

    def get_history_turns(self, session_id: str = 'default') -> int:
        """获取指定会话的对话轮数。"""
        conversation = self.sessions.get(session_id, [])
        return len(conversation) // 2
