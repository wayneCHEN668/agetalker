import asyncio
import json
import logging
import time
from typing import AsyncGenerator, Optional
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
    CRISIS_VIGILANCE_TURNS,
    TTS_PARAMS_MAP,
    CATEGORY_TTS_PARAMS_MAP,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    ROUTER_TEMPERATURE,
    ROUTER_MAX_TOKENS,
    ROUTER_CONTEXT_TURNS,
    ROUTER_EXTRA_BODY,
    MEMORY_SUMMARY_EVERY_N_MSGS,
    SESSION_OPENING_TURNS,
    SESSION_CLOSING_AFTER_MIN,
    MAX_CONSECUTIVE_QUESTIONS,
)
from prompts.templates import (
    build_normal_prompt,
    build_crisis_prompt,
    build_closing_prompt,
    build_proactive_prompt,
    ROUTER_SYSTEM_PROMPT,
    build_router_user_prompt,
    resolve_strategy_id,
    CATEGORY_STRATEGY_MAP,
    build_elicitation_block,
)
from services.profile_schema import is_askable
from services.elicitation import MODE_NONE, plan_elicitation
from services.proactive import ProactiveGuard

logger = logging.getLogger(__name__)

# 情绪效价（valence）变化到多少算"好转"/"下降"。低于这个幅度视为持平——
# 单轮 valence 本来就有噪声，阈值太小会把噪声当成效果。
_VALENCE_IMPROVED_DELTA = 0.10
_VALENCE_WORSENED_DELTA = -0.10


def _grade_effect(delta: float) -> str:
    """把两轮之间的 valence 变化归成三档，供路由判断要不要推进策略。"""
    if delta >= _VALENCE_IMPROVED_DELTA:
        return '好转'
    if delta <= _VALENCE_WORSENED_DELTA:
        return '下降'
    return '持平'


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

    v4 -> v5 变更（类别延续判定，解决"叙事中间的中性句被误判脱离原类别"）：
    - 新增 self.last_category：{session_id: 上一轮判定的 category}，与
      self.strategy_history 平级维护。危机轮不更新这个值——危机结束后恢复
      正常对话，应该参考的是危机发生前的类别，不是 "crisis" 本身。
    - _route_category() 新增 last_category 参数，转发给 build_router_user_prompt，
      配合 ROUTER_SYSTEM_PROMPT 里新增的"类别延续判定"规则（不对称：进入敏感
      类别门槛不变，退出敏感类别需要更明确的信号），让路由模型正确把一句字面
      中性的话识别成"同一段叙事的延续"，而不是逐句独立判断导致中途误判成 neutral。
    """

    def __init__(self, memory_service=None, profile_service=None):
        # 长程记忆服务（MemoryService）。为 None 时整套记忆逻辑静默跳过，
        # 对话本身照常工作——记忆是增强能力，不是对话的前置依赖。
        self.memory = memory_service
        # 画像服务。为 None 时整套采集逻辑静默跳过，对话照常工作——
        # 和记忆一样，画像是增强能力，不是对话的前置依赖。
        self.profile = profile_service
        # 后台任务引用：asyncio 只持弱引用，不自己存着的话任务可能被 GC 掉
        self._bg_tasks: set = set()
        # 已滑出历史窗口、等待压缩进摘要的消息：{session_id: [msg, ...]}
        self._pending_summary: dict[str, list[dict]] = {}
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
        # 策略延续状态：{session_id: {category: {strategy_id: {'count', 'last_effect'}}}}
        self.strategy_history: dict[str, dict[str, dict[str, dict]]] = {}
        # 上一轮选中的策略及选它时的情绪 valence，用于下一轮结算效果
        self.last_strategy: dict[str, dict] = {}
        # 类别延续状态：{session_id: 上一轮判定的 category}（crisis 轮不更新这个值，
        # 危机结束后恢复正常对话时，应该参考的是危机发生前的类别，不是 "crisis" 本身）
        self.last_category: dict[str, str] = {}
        # 危机警惕期剩余轮数：{session_id: 剩余轮数}。命中危机时置为
        # CRISIS_VIGILANCE_TURNS，之后每轮递减到 0。见 _resolve_crisis_state()。
        self.crisis_vigilance: dict[str, int] = {}
        # 会话弧线状态：{session_id: {started_at, turn_count, consecutive_questions}}
        self.session_meta: dict[str, dict] = {}
        # 主动开口护栏（夜间静默 / 每日上限 / 无人应答）。放在服务端而不是前端：
        # 前端可以被绕过、可以有 bug、可以在多个标签页里各跑一份计时器。
        self.proactive_guard = ProactiveGuard()
        logger.info("LLM 服务初始化完成 ✅ (生成: Qwen/AsyncOpenAI | 路由: DeepSeek/AsyncOpenAI | 策略延续: 已启用 | 类别延续: 已启用 | 危机警惕期: 已启用)")

    # ─── 路由 LLM ───────────────────────────────────────────────────────────

    async def _route_category(
        self,
        user_text: str,
        context: str = "",
        last_category: str = "",
        used_strategies: str = "",
        crisis_recent: bool = False,
        strategy_feedback: str = "",
    ) -> tuple[str, str, str, str]:
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
            last_category: 上一轮判定的心理类别（由 self.last_category 提供）。
                解决"叙事中间的中性陈述句被误判为脱离原类别"的问题——只给原始
                对话文本不够，模型仍可能逐句独立判断，必须显式告诉它"上一轮
                判的是什么"，配合 ROUTER_SYSTEM_PROMPT 里的"类别延续判定"规则，
                才能让它正确识别"同一段叙事的延续"。
            used_strategies: 这个会话里各类别已用过的策略 id（由 _format_used_strategies
                构建），供路由模型参考"该不该推进到下一步"，不是必须避开的黑名单。
            crisis_recent: 是否处于危机警惕期。为 True 时提示路由在"退出敏感类别"
                上更保守——刚出过高危信号的对话里，一句表面平静的话不足以证明
                风险已经过去。

        Returns:
            (category, matched_signals, strategy_id, slot_hint)
            strategy_id 为空字符串时，表示路由没有给出有效策略（is_crisis、解析
            失败、或返回的 id 不在该类别策略列表内），下游会通过 resolve_strategy_id()
            兜底为该类别的第一条策略。
            slot_hint 为空字符串时，表示这一轮没有采集线索（没提到、拿不准、
            或返回了非法字段名）。
        """
        try:
            resp = await self.router_client.chat.completions.create(
                model       = DEEPSEEK_MODEL,
                messages    = [
                    {'role': 'system', 'content': ROUTER_SYSTEM_PROMPT},
                    {'role': 'user',   'content': build_router_user_prompt(
                        user_text,
                        conversation_context=context,
                        last_category=last_category,
                        used_strategies=used_strategies,
                        crisis_recent=crisis_recent,
                        strategy_feedback=strategy_feedback,
                    )},
                ],
                temperature = ROUTER_TEMPERATURE,
                max_tokens  = ROUTER_MAX_TOKENS,
                response_format = {'type': 'json_object'},
                extra_body  = ROUTER_EXTRA_BODY,
            )
            raw = resp.choices[0].message.content
            if not raw:
                logger.warning("路由调用返回空内容，降级为 neutral")
                return 'neutral', '', '', ''

            result = json.loads(raw.strip())
            category = result.get('category', 'neutral')
            is_crisis = result.get('is_crisis', False)
            matched_signals = result.get('matched_signals', '')
            strategy_id = result.get('strategy_id', '')

            # 采集线索：非法字段名一律当空（设计文档 §4.1）。
            # 采集是增强能力，报错的线索宁可丢掉，也不能让它污染这一轮。
            slot_hint = result.get('slot_hint', '') or ''
            if not is_askable(slot_hint):
                slot_hint = ''

            if is_crisis or category == 'crisis':
                return 'crisis', matched_signals, '', ''

            if category not in CATEGORY_STRATEGY_MAP:
                logger.warning(f"路由模型返回未知类别 '{category}'，降级为 neutral")
                return 'neutral', matched_signals, '', slot_hint

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
            return category, matched_signals, strategy_id, slot_hint

        except Exception as e:
            logger.error(f"路由调用失败: {e}，降级为 neutral")
            return 'neutral', '路由暂不可用', '', ''

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
            f"{'老人' if msg['role'] == 'user' else '蘅小年'}：{msg['content'][:60]}"
            for msg in recent
        ]
        return '\n'.join(lines)

    def _format_used_strategies(self, session_id: str) -> str:
        """
        把这个会话各类别已用过的策略拼成字符串，传给路由模型做参考。

        格式形如 "anger：pause_breathe×3(上次持平)，uncover_need×1(上次好转)"。

        以前这里存的是一条条原始记录的列表、并且按最近 8 条截断——一小时对话里
        某个类别可能被访问 30 次以上，早期记录会滚出窗口，路由于是"忘了"开头
        用过什么，第 50 分钟又从第一条策略重新做一遍。现在按 strategy_id 聚合
        成"次数 + 最近一次效果"，条目数天然不超过该类别的策略条数（≤6），
        再长的会话也不会滚掉。
        """
        history = self.strategy_history.get(session_id)
        if not history:
            return ''
        parts = []
        for cat, stats in history.items():
            if not stats:
                continue
            items = ', '.join(
                f"{sid}×{s['count']}"
                + (f"(上次{s['last_effect']})" if s.get('last_effect') else '')
                for sid, s in stats.items()
            )
            parts.append(f"{cat}：{items}")
        return '；'.join(parts)

    def _settle_last_strategy(self, session_id: str, emotion: dict) -> str:
        """
        结算上一轮策略的效果，并返回一句给路由看的反馈描述。

        情绪服务算出的 valence 是判断"上一步干预有没有起作用"唯一的客观信号，
        但它以前只被送去生成模型当语气参考，从没送达路由——于是路由每轮都在
        没有任何效果反馈的情况下决定要不要推进策略，等于开环。这里把它接上。
        """
        last = self.last_strategy.get(session_id)
        if not last:
            return ''

        current_valence = float(emotion.get('valence', 0.5))
        effect = _grade_effect(current_valence - last['valence'])

        stats = (
            self.strategy_history
            .setdefault(session_id, {})
            .setdefault(last['category'], {})
            .get(last['strategy_id'])
        )
        if stats is not None:
            stats['last_effect'] = effect

        return f"{last['strategy_id']}（{last['category']}）用完之后，情绪{effect}"

    # ─── 会话弧线与节奏 ─────────────────────────────────────────────────────

    def _get_session_meta(self, session_id: str) -> dict:
        """取会话弧线状态，首轮时初始化。"""
        if session_id not in self.session_meta:
            self.session_meta[session_id] = {
                'started_at': datetime.now(timezone.utc),
                'turn_count': 0,
                'consecutive_questions': 0,
                # ── 采集节奏（设计文档 §4.2/§4.3）──
                'elicited_count': 0,      # 本会话已主动起了几个话头（不含 address）
                'last_elicit_turn': -999, # 上次主动采集在第几轮，用于冷却
                'address_asked': False,   # 本会话是否已问过称呼
            }
        return self.session_meta[session_id]

    def get_phase(self, session_id: str) -> str:
        """
        当前会话阶段：opening / deepening / closing。

        暖场按轮数判定（前几轮），收束按时长判定（聊了多久）——一小时的对话
        该不该收尾，取决于过了多长时间，而不是说了多少句。
        """
        meta = self._get_session_meta(session_id)
        elapsed_min = (
            datetime.now(timezone.utc) - meta['started_at']
        ).total_seconds() / 60.0
        if elapsed_min >= SESSION_CLOSING_AFTER_MIN:
            return 'closing'
        if meta['turn_count'] < SESSION_OPENING_TURNS:
            return 'opening'
        return 'deepening'

    def _should_restrain_questions(self, session_id: str) -> bool:
        """连续以问句收尾达到阈值时，这一轮跳过 CARE 的 E 步骤。"""
        return self._get_session_meta(session_id)['consecutive_questions'] >= MAX_CONSECUTIVE_QUESTIONS

    def _note_reply_shape(self, session_id: str, reply: str):
        """记录这条回复是不是以问句结尾，供下一轮判断要不要收着点问。"""
        meta = self._get_session_meta(session_id)
        if reply.rstrip().endswith(('？', '?')):
            meta['consecutive_questions'] += 1
        else:
            meta['consecutive_questions'] = 0

    # ─── 后台任务 ───────────────────────────────────────────────────────────

    def _spawn_bg(self, coro):
        """
        起一个后台任务并持有引用。

        记忆的抽取和摘要都放在这里跑，不占当轮回复的关键路径——代价只是本轮
        说的事实从下一轮开始可用，对连贯性没有实质影响。
        """
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _schedule_memory_work(
        self,
        elder_id: str,
        session_id: str,
        user_text: str,
        dropped: list[dict],
        crisis: bool,
    ):
        """安排本轮的记忆后台工作：事实抽取 + （必要时）滚动摘要压缩。"""
        # 画像抽取：和记忆抽取并行的独立后台调用，不受 self.memory 是否启用影响
        # ——两个服务解耦，各自可独立失败/独立开关。都在后台，不占关键路径。
        if self.profile is not None and not crisis and user_text.strip():
            self._spawn_bg(self.profile.observe_turn(elder_id, user_text))

        if self.memory is None:
            return

        # 危机轮次不写入长程记忆。
        # 对话历史里仍然保留（下一轮需要这个语境，抹掉反而更危险），但不让危机
        # 内容沉淀成跨会话的永久记录，以后也不会被回指出来。
        if not crisis:
            self._spawn_bg(self.memory.observe_turn(elder_id, user_text))

        if dropped:
            pending = self._pending_summary.setdefault(session_id, [])
            pending.extend(dropped)
            # 攒够一批再压缩，避免历史满了之后每轮都多一次 LLM 调用
            if len(pending) >= MEMORY_SUMMARY_EVERY_N_MSGS:
                batch = list(pending)
                pending.clear()
                self._spawn_bg(self.memory.fold_into_summary(session_id, batch))

    def _record_strategy_use(
        self, session_id: str, category: str, strategy_id: str, emotion: dict,
    ):
        """
        记录这一轮实际生效的策略（必须是 resolve_strategy_id() 兜底之后的值，
        不能是路由模型原始返回的、可能无效的值），供下一轮路由判断参考。

        同时记下选这条策略时的 valence——下一轮拿新的 valence 和它比，就知道
        这一步到底有没有起作用（见 _settle_last_strategy）。
        """
        per_category = self.strategy_history.setdefault(session_id, {}).setdefault(category, {})
        stats = per_category.setdefault(strategy_id, {'count': 0, 'last_effect': ''})
        stats['count'] += 1

        self.last_strategy[session_id] = {
            'category': category,
            'strategy_id': strategy_id,
            'valence': float(emotion.get('valence', 0.5)),
        }

    # ─── 主入口：流式生成回复 ────────────────────────────────────────────────

    async def stream_reply(
        self,
        user_text: str,
        emotion:   dict,
        session_id: str = 'default',
        elder_id:   str = 'default_elder',
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
            session_id: 会话 ID（每次对话新生成，隔离对话历史/策略延续/类别延续）
            elder_id:   老人 ID（跨会话稳定，长程记忆按它归档）

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

        # 分段计时：一轮回复慢在哪一段，光靠感觉判断不出来
        _t0 = time.monotonic()

        # ── 步骤 2：关键词危机检测（硬性熔断层，第一优先级，不依赖任何 LLM）────
        category = 'neutral'      # 默认值（危机被拦截、或路由失败兜底时使用）
        matched_signals = ''
        strategy_id = ''
        strategy_name = ''
        slot_hint = ''            # 路由未跑（危机命中）时保持空
        crisis = self._check_crisis(user_text)
        # 本轮开始时是否已处于警惕期——要在下面可能重新置位之前先取出来
        crisis_vigilant = self._is_crisis_vigilant(session_id)
        if crisis:
            logger.warning(f"⚠️  危机信号触发 (关键词) | Session: {session_id} | 文本: {user_text[:50]}")
            self._dispatch_crisis_event(user_text, session_id)

        # ── 步骤 3：路由模型判断心理类别 + 选策略（仅在关键词层未命中时才需要）──
        if not crisis:
            context = self._build_router_context(conversation, ROUTER_CONTEXT_TURNS)
            used_strategies = self._format_used_strategies(session_id)
            last_category = self.last_category.get(session_id, '')
            # 先结算上一条策略的效果，再让路由决定这一轮该不该往下推进
            strategy_feedback = self._settle_last_strategy(session_id, emotion)
            category, matched_signals, raw_strategy_id, slot_hint = await self._route_category(
                user_text, context, last_category, used_strategies,
                crisis_recent=crisis_vigilant,
                strategy_feedback=strategy_feedback,
            )
            logger.info(f"⏱ 路由({DEEPSEEK_MODEL}) {(time.monotonic()-_t0)*1000:.0f}ms")
            if category == 'crisis':
                crisis = True
                logger.warning(f"⚠️  危机信号触发 (路由 LLM) | Session: {session_id} | 文本: {user_text[:50]}")
                self._dispatch_crisis_event(user_text, session_id)
                matched_signals = ''
                strategy_id = ''
            else:
                # 兜底校验，记录的必须是这个最终生效的值，不是路由原始返回值
                strategy_id = resolve_strategy_id(category, raw_strategy_id)
                self._record_strategy_use(session_id, category, strategy_id, emotion)
                # 查找策略中文名（供前端展示，避免前端再维护一份策略名称映射）
                _cat_cfg = CATEGORY_STRATEGY_MAP.get(category, CATEGORY_STRATEGY_MAP['neutral'])
                _strategy = next(
                    (s for s in _cat_cfg['strategies'] if s['id'] == strategy_id),
                    _cat_cfg['strategies'][0],
                )
                strategy_name = _strategy['name']
                # 危机轮不更新 last_category：危机结束后恢复正常对话，应该参考的是
                # 危机发生前的类别，不是 "crisis" 本身（crisis 也不在 CATEGORY_STRATEGY_MAP
                # 里，传给路由当 last_category 它也认不出来）
                self.last_category[session_id] = category

        # ── 步骤 3.5：更新危机警惕期状态 ─────────────────────────────────────
        if crisis:
            # 本轮走完整危机 prompt，不需要再叠加警惕段；警惕期从下一轮开始生效
            self._enter_crisis_vigilance(session_id)
            crisis_vigilant = False
        else:
            self._decay_crisis_vigilance(session_id)

        # ── 步骤 3.6：采集规划（纯逻辑，不调 LLM）─────────────────────────────
        meta = self._get_session_meta(session_id)
        # 记下本轮开始时的值——_note_reply_shape() 稍后会用本轮回复更新这个
        # 计数器，届时它反映的就是"这一轮"而不是"上一轮"了，必须提前存好。
        ai_asked_question_prev_turn = meta['consecutive_questions'] > 0
        elicit_block = ''
        plan = None
        if self.profile is not None:
            try:
                plan = plan_elicitation(
                    self.profile.get_profile(elder_id),
                    slot_hint                  = slot_hint,
                    category                   = category,
                    phase                      = self.get_phase(session_id),
                    crisis                     = crisis,
                    crisis_vigilant            = crisis_vigilant,
                    restrain_questions         = self._should_restrain_questions(session_id),
                    turns_since_last_elicit    = meta['turn_count'] - meta['last_elicit_turn'],
                    elicited_this_session      = meta['elicited_count'],
                    address_asked_this_session = meta['address_asked'],
                )
                if plan.mode != MODE_NONE:
                    elicit_block = build_elicitation_block(plan.mode, plan.slot, plan.is_stale)
            except Exception as e:
                # 采集失败不影响对话（设计文档 §9）
                logger.warning(f"采集规划失败（忽略，不影响对话）: {e}")
                plan = None

        # ── 步骤 4：构建 System Prompt ──────────────────────────────────────
        if crisis:
            system_prompt = build_crisis_prompt()
        else:
            system_prompt = build_normal_prompt(
                category, emotion, matched_signals, strategy_id, crisis_vigilant,
                memory_context  = self.memory.get_context(elder_id) if self.memory else '',
                session_summary = self.memory.get_summary(session_id) if self.memory else '',
                phase              = self.get_phase(session_id),
                restrain_questions = self._should_restrain_questions(session_id),
                profile_context   = self.profile.get_context(elder_id) if self.profile else '',
                elicitation_block = elicit_block,
            )
            if crisis_vigilant:
                logger.info(f"危机警惕期生效 | Session: {session_id} | 剩余 {self.crisis_vigilance.get(session_id, 0)} 轮")

        # ── 步骤 4.5：先发 meta 事件（解锁前端逐句 TTS 流水线）───────────────
        # category / strategy_name / tts_params 在这里已经全部算出来了，早于调用
        # 生成模型。提前发给前端，前端才能在流式输出过程中「凑满一句就合成一句」，
        # 不必等整段生成结束——后者每轮多出好几秒静默，一小时对话里累积起来是
        # 体验上最伤的一处（设计文档 §4.2 要求的首句流水线）。
        # done 事件仍携带同样字段，老前端不受影响。
        yield {
            'type':          'meta',
            'crisis':        crisis,
            'category':      category if not crisis else 'crisis',
            'strategy_id':   strategy_id,
            'strategy_name': strategy_name,
            'tts_params':    self._get_tts_params_by_category(category, crisis),
        }

        # ── 步骤 5：追加用户消息到历史 ──────────────────────────────────────
        conversation.append({'role': 'user', 'content': user_text})

        # ── 步骤 6：裁剪历史，保留最近 N 轮 ────────────────────────────────
        # 被裁掉的消息不是丢掉就完了——它们会被压缩进滚动摘要，这是长对话里
        # 「前面聊过什么」唯一的去处
        max_msgs = LLM_MAX_HISTORY_TURNS * 2
        dropped: list[dict] = []
        if len(conversation) > max_msgs:
            dropped = conversation[:-max_msgs]
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
        _t_gen = time.monotonic()
        async for chunk in stream:
            delta_text = chunk.choices[0].delta.content or ''
            if delta_text:
                if not full_reply:
                    logger.info(
                        f"⏱ 生成首字({QWEN_MODEL}) {(time.monotonic()-_t_gen)*1000:.0f}ms "
                        f"| 本轮累计 {(time.monotonic()-_t0)*1000:.0f}ms"
                    )
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
            self._note_reply_shape(session_id, full_reply)

        self._get_session_meta(session_id)['turn_count'] += 1

        # ── 步骤 10.4：推进采集计数（问出去了才算，规划器只是打算）──────────────
        if plan is not None and plan.mode != MODE_NONE and self.profile is not None:
            try:
                self.profile.note_asked(elder_id, plan.slot)
                if plan.slot == 'address':
                    # address 不计入会话名额：它不是采集，是自我介绍的一部分
                    meta['address_asked'] = True
                else:
                    meta['elicited_count'] += 1
                    meta['last_elicit_turn'] = meta['turn_count']
            except Exception as e:
                logger.warning(f"采集计数推进失败（忽略）: {e}")

        # ── 步骤 10.6：行为观测（同步、纯计数，不调 LLM）─────────────────────
        if self.profile is not None and not crisis:
            try:
                # ai_asked_question 用的是**上一轮**回复是否以问句结尾——
                # 老人这一句正是对那一句的回应
                self.profile.observe_behavior(
                    elder_id, user_text, category,
                    ai_asked_question=ai_asked_question_prev_turn,
                )
            except Exception as e:
                logger.warning(f"行为观测失败（忽略）: {e}")

        # ── 步骤 10.5：安排记忆的后台工作（不阻塞本轮回复）────────────────────
        self._schedule_memory_work(elder_id, session_id, user_text, dropped, crisis)

        # ── 步骤 11：生成完毕信号 ─────────────────────────────────────────────
        yield {
            'type':          'done',
            'full_text':     full_reply,
            'crisis':        crisis,
            'category':      category if not crisis else 'crisis',
            'strategy_id':   strategy_id,
            'strategy_name': strategy_name,
            'tts_params':    self._get_tts_params_by_category(category, crisis),
        }

    # ─── 收束仪式 ───────────────────────────────────────────────────────────

    async def stream_closing(
        self,
        session_id: str = 'default',
        elder_id:   str = 'default_elder',
    ) -> AsyncGenerator[dict, None]:
        """
        流式生成一段收尾告别。

        以前"结束对话"就是 2.5 秒后把界面清空。把一段哀伤或抑郁的叙事打开之后
        这样收场，临床上是有害的——你不会把一个刚敞开心扉的人晾在那儿。这里
        用本次会话的摘要生成一段有回顾、有肯定、有约定的告别。

        事件结构和 stream_reply 一致（meta → delta... → done），前端可以直接
        复用同一条播放通路。
        """
        summary = self.memory.get_summary(session_id) if self.memory else ''
        context = self.memory.get_context(elder_id) if self.memory else ''
        system_prompt = build_closing_prompt(summary, context)

        # 告别一律用最平缓的语气，不跟着当前类别走
        tts_params = CATEGORY_TTS_PARAMS_MAP['neutral']
        yield {
            'type': 'meta', 'crisis': False, 'category': 'closing',
            'strategy_id': '', 'strategy_name': '道别', 'tts_params': tts_params,
        }

        try:
            stream = await self.client.chat.completions.create(
                model       = QWEN_MODEL,
                messages    = [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user',   'content': '我们今天就聊到这儿吧。'},
                ],
                stream      = True,
                max_tokens  = LLM_MAX_TOKENS,
                temperature = LLM_TEMPERATURE,
                top_p       = LLM_TOP_P,
            )
        except Exception as e:
            logger.error(f"收尾生成失败 (Session: {session_id}): {e}")
            # 生成失败也不能没有告别——退回一句固定的
            fallback = '今天跟你聊得挺好的。你早点歇着，明儿这个点我还在这儿。'
            yield {'type': 'delta', 'text': fallback, 'crisis': False}
            yield {'type': 'done', 'full_text': fallback, 'crisis': False,
                   'category': 'closing', 'strategy_id': '', 'strategy_name': '道别',
                   'tts_params': tts_params}
            return

        full_reply = ''
        async for chunk in stream:
            delta_text = chunk.choices[0].delta.content or ''
            if delta_text:
                full_reply += delta_text
                yield {'type': 'delta', 'text': delta_text, 'crisis': False}

        yield {
            'type': 'done', 'full_text': full_reply, 'crisis': False,
            'category': 'closing', 'strategy_id': '', 'strategy_name': '道别',
            'tts_params': tts_params,
        }

    # ─── 主动开口 ───────────────────────────────────────────────────────────

    async def stream_proactive(
        self,
        session_id: str = 'default',
        elder_id:   str = 'default_elder',
        trigger:    str = 'scheduled',
    ) -> AsyncGenerator[dict, None]:
        """AI 主动说一段话（定时招呼 / 沉默唤起）。

        形状和 stream_closing 完全一致（meta → delta... → done），前端复用
        同一条播放通路。

        与 closing 的一个关键差别：**生成失败时不兜底说一句**。closing 失败
        必须有兜底（不能把刚敞开心扉的人晾在那儿），proactive 失败必须没有
        兜底——不能因为失败就反复出声（设计文档 §9）。
        """
        address  = self.profile.get_address(elder_id) if self.profile else '您'
        memory   = self.memory.get_context(elder_id) if self.memory else ''
        prof_ctx = self.profile.get_context(elder_id) if self.profile else ''

        # 主动开口的时刻没有正在进行的叙事，是采集的最佳窗口（设计文档 §6.2）
        meta = self._get_session_meta(session_id)
        elicit_block, plan = '', None
        if self.profile is not None:
            try:
                plan = plan_elicitation(
                    self.profile.get_profile(elder_id),
                    slot_hint                  = '',
                    category                   = 'neutral',
                    phase                      = 'opening',
                    crisis                     = False,
                    crisis_vigilant            = self._is_crisis_vigilant(session_id),
                    restrain_questions         = self._should_restrain_questions(session_id),
                    turns_since_last_elicit    = meta['turn_count'] - meta['last_elicit_turn'],
                    elicited_this_session      = meta['elicited_count'],
                    address_asked_this_session = meta['address_asked'],
                )
                if plan.mode != MODE_NONE:
                    elicit_block = build_elicitation_block(plan.mode, plan.slot, plan.is_stale)
            except Exception as e:
                logger.warning(f"主动开口采集规划失败（忽略）: {e}")
                plan = None

        system_prompt = build_proactive_prompt(
            address, trigger,
            memory_context    = memory,
            profile_context   = prof_ctx,
            elicitation_block = elicit_block,
        )

        # 主动开口一律用平缓语气，不跟着任何类别走
        tts_params = CATEGORY_TTS_PARAMS_MAP['neutral']
        yield {
            'type': 'meta', 'crisis': False, 'category': 'proactive',
            'strategy_id': '', 'strategy_name': '主动问候', 'tts_params': tts_params,
        }

        try:
            stream = await self.client.chat.completions.create(
                model       = QWEN_MODEL,
                messages    = [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user',   'content': '（现在轮到你先开口。）'},
                ],
                stream      = True,
                max_tokens  = LLM_MAX_TOKENS,
                temperature = LLM_TEMPERATURE,
                top_p       = LLM_TOP_P,
            )
        except Exception as e:
            # 静默放弃：不重试、不兜底说一句
            logger.warning(f"主动开口生成失败，本次放弃 (Session: {session_id}): {e}")
            yield {'type': 'done', 'full_text': '', 'crisis': False,
                   'category': 'proactive', 'strategy_id': '',
                   'strategy_name': '主动问候', 'tts_params': tts_params}
            return

        full_reply = ''
        async for chunk in stream:
            delta_text = chunk.choices[0].delta.content or ''
            if delta_text:
                full_reply += delta_text
                yield {'type': 'delta', 'text': delta_text, 'crisis': False}

        # 主动说的话必须进历史，否则老人回应时模型不知道自己刚说了什么
        if full_reply:
            self.sessions.setdefault(session_id, []).append(
                {'role': 'assistant', 'content': full_reply}
            )
            self._note_reply_shape(session_id, full_reply)
            if plan is not None and plan.mode != MODE_NONE and self.profile is not None:
                try:
                    self.profile.note_asked(elder_id, plan.slot)
                    if plan.slot == 'address':
                        meta['address_asked'] = True
                    else:
                        meta['elicited_count'] += 1
                        meta['last_elicit_turn'] = meta['turn_count']
                except Exception as e:
                    logger.warning(f"主动开口采集计数推进失败（忽略）: {e}")

        yield {
            'type': 'done', 'full_text': full_reply, 'crisis': False,
            'category': 'proactive', 'strategy_id': '',
            'strategy_name': '主动问候', 'tts_params': tts_params,
        }

    def can_speak_proactively(self, session_id: str, elder_id: str) -> tuple[bool, str]:
        """这一刻能不能主动开口。返回 (可以吗, 不可以的原因)。"""
        return self.proactive_guard.can_speak(
            elder_id, crisis_vigilant=self._is_crisis_vigilant(session_id),
        )

    def note_proactive_answered(self, elder_id: str) -> None:
        self.proactive_guard.note_answered(elder_id)

    def note_proactive_no_answer(self, elder_id: str) -> None:
        self.proactive_guard.note_no_answer(elder_id)

    # ─── 危机检测 ───────────────────────────────────────────────────────────

    def _check_crisis(self, text: str) -> bool:
        """关键词匹配危机检测。零延迟，不依赖任何 LLM 调用。"""
        return any(kw in text for kw in CRISIS_KEYWORDS)

    # ─── 危机警惕期（设计文档 §9.3）────────────────────────────────────────────
    #
    # 命中危机的那一轮走完整的危机 prompt；之后 CRISIS_VIGILANCE_TURNS 轮即使
    # 不再出现危机信号，也在常规 prompt 上叠加一段警惕说明。
    #
    # 这里刻意只做「按轮数自然衰减」，不做「路由判定情绪好转就提前解除」：
    # 刚经历过高危信号的人，表面上说「我没事了」恰恰是最典型的表现，用这个信号
    # 提前解除警惕，等于在最不该松手的时候松手。多警惕两轮的代价远小于反过来。

    def _is_crisis_vigilant(self, session_id: str) -> bool:
        """当前是否处于危机警惕期。"""
        return self.crisis_vigilance.get(session_id, 0) > 0

    def _enter_crisis_vigilance(self, session_id: str):
        """命中危机，开启/重置警惕期。"""
        self.crisis_vigilance[session_id] = CRISIS_VIGILANCE_TURNS

    def _decay_crisis_vigilance(self, session_id: str):
        """未命中危机的一轮，警惕期计数递减。"""
        remaining = self.crisis_vigilance.get(session_id, 0)
        if remaining > 0:
            self.crisis_vigilance[session_id] = remaining - 1

    def _dispatch_crisis_event(self, user_text: str, session_id: str):
        """自动检测到危机信号时分发事件。"""
        self._write_event({
            'type':       'crisis_alert',
            'session_id': session_id,
            'user_text':  user_text[:100],
        })

    def dispatch_escalation(self, session_id: str, source: str = 'ui') -> dict:
        """
        界面上主动点击「联系护理员」时分发事件。

        和自动检测出的危机走同一个出口——护工端轮询一个目录就能同时拿到
        「系统判定的危机」和「本人主动求助」两类事件。
        """
        return self._write_event({
            'type':       'caregiver_requested',
            'session_id': session_id,
            'source':     source,
        })

    def _write_event(self, event: dict) -> dict:
        """
        事件分发的统一出口。

        当前实现：结构化日志 + JSON 事件文件（供监控/通知服务轮询）。
        后续接入家庭沟通模块时，只需要替换这一个方法为 MQTT/Webhook/推送调用。

        文件名里带上事件类型，避免同一秒内的两类事件互相覆盖。
        """
        event['timestamp'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
        # 1. 结构化日志（供日志系统采集）
        logger.critical(f"CRISIS_EVENT: {json.dumps(event, ensure_ascii=False)}")
        # 2. 事件文件（供外部监控轮询，如护工端 App）
        try:
            events_dir = Path('data/crisis_events')
            events_dir.mkdir(parents=True, exist_ok=True)
            ts = event['timestamp'][:19].replace(':', '-')
            event_file = events_dir / f"{ts}_{event['session_id']}_{event['type']}.json"
            event_file.write_text(json.dumps(event, ensure_ascii=False, indent=2),
                                 encoding='utf-8')
            logger.info(f"事件已写入: {event_file}")
        except Exception as e:
            logger.error(f"写入事件文件失败: {e}")
        return event

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

    def truncate_last_reply(self, session_id: str, spoken_text: str) -> bool:
        """
        老人插话打断时，把历史里最后一条回复截断成**实际播出去**的那部分。

        不做这件事的话，历史里存的是完整回复，模型以为自己整段都说完了，
        下一轮可能出现「我刚才跟你说的那个……」——而老人根本没听到后半截。
        对陪伴场景来说这不是小瑕疵：它会让老人觉得对方在说些莫名其妙的话。

        spoken_text 为空（一个字都没播出去）时，整条回复从历史里移除。

        Returns:
            True 表示确实改动了历史，False 表示没有可截断的回复。
        """
        conversation = self.sessions.get(session_id)
        if not conversation or conversation[-1]['role'] != 'assistant':
            return False

        spoken = (spoken_text or '').strip()
        original = conversation[-1]['content']
        if spoken == original:
            return False

        if spoken:
            conversation[-1]['content'] = spoken
        else:
            conversation.pop()

        # 提问节制是按"回复是不是以问句结尾"统计的，截断后要按实际说出口的重算
        meta = self._get_session_meta(session_id)
        if spoken.endswith(('？', '?')):
            pass                       # 截断后仍是问句，计数不变
        else:
            meta['consecutive_questions'] = 0

        logger.info(
            f"回复被打断，历史已截断 | Session: {session_id} | "
            f"{len(original)} 字 → {len(spoken)} 字"
        )
        return True

    async def close_session(self, session_id: str = 'default', elder_id: str = ''):
        """
        会话正常结束时调用：把还没压缩的历史并进摘要，再把本次摘要留档进台账。

        必须在 reset() 之前调用——reset() 会把滚动摘要一起清掉。留档之后，
        下一次对话就能回指「上次咱们聊到…」。
        """
        if self.memory is None or not elder_id:
            return
        pending = self._pending_summary.pop(session_id, [])
        if pending:
            await self.memory.fold_into_summary(session_id, pending)
        self.memory.close_session(elder_id, session_id)

    def reset(self, session_id: str = 'default'):
        """重置指定会话的对话历史、策略延续状态和类别延续状态。"""
        had_session = session_id in self.sessions
        if had_session:
            self.sessions[session_id].clear()
        self.strategy_history.pop(session_id, None)
        self.last_strategy.pop(session_id, None)
        self.last_category.pop(session_id, None)
        self.crisis_vigilance.pop(session_id, None)
        self.session_meta.pop(session_id, None)
        self._pending_summary.pop(session_id, None)
        if self.memory is not None:
            self.memory.reset_session(session_id)
        if had_session:
            logger.info(f"会话 {session_id} 历史与延续状态已重置")
        else:
            logger.info(f"会话 {session_id} 不存在，无需重置")

    def get_history_turns(self, session_id: str = 'default') -> int:
        """获取指定会话的对话轮数。"""
        conversation = self.sessions.get(session_id, [])
        return len(conversation) // 2
