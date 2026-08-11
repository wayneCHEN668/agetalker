import sys
import os
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_service import LLMService


@pytest.fixture(autouse=True)
def no_real_crisis_files():
    """
    别让测试往项目的 data/crisis_events/ 里写真实事件文件。

    危机相关的测试会真的走到事件分发，之前每跑一次测试就在仓库里留下一批
    垃圾 JSON。事件写入本身在别处验证，这里只需要它不落盘。
    """
    with patch.object(LLMService, '_write_event', return_value={}):
        yield


@pytest.fixture
def llm_service():
    """初始化 LLMService，mock 掉 AsyncOpenAI 客户端。"""
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        service = LLMService()
    return service


def _make_stream(texts: list[str]):
    """构造一个假的 Qwen 流式响应（异步可迭代）。"""
    chunks = []
    for t in texts:
        c = MagicMock()
        c.choices[0].delta.content = t
        chunks.append(c)

    class _Stream:
        def __aiter__(self):
            async def gen():
                for c in chunks:
                    yield c
            return gen()

    return _Stream()


def test_crisis_detection(llm_service):
    """验证危机词检测逻辑。"""
    assert llm_service._check_crisis("我不想活了") is True
    assert llm_service._check_crisis("活着没意思") is True
    assert llm_service._check_crisis("没人需要我了") is True   # v2 新增
    assert llm_service._check_crisis("交代后事") is True       # v2 新增
    assert llm_service._check_crisis("今天天气不错") is False
    assert llm_service._check_crisis("我想吃苹果") is False


def test_tts_params_mapping(llm_service):
    """验证情绪到 TTS 参数的映射。"""
    # 危机模式：应使用 _crisis 参数
    assert llm_service._get_tts_params({}, True)['style'] == 'gentle'
    assert llm_service._get_tts_params({}, True)['speed'] == 0.82

    # 正常模式
    assert llm_service._get_tts_params({'label': 'happy'}, False)['style'] == 'cheerful'
    assert llm_service._get_tts_params({'label': 'sad'}, False)['pitch'] == -2
    assert llm_service._get_tts_params({'label': 'neutral'}, False)['style'] == 'neutral'


def test_multi_session_isolation(llm_service):
    """验证多会话历史隔离。"""
    llm_service.sessions['user1'] = [{'role': 'user', 'content': 'hello'}]
    llm_service.sessions['user2'] = [{'role': 'user', 'content': 'hi'}]

    assert len(llm_service.sessions['user1']) == 1
    llm_service.reset('user1')
    assert len(llm_service.sessions['user1']) == 0
    assert len(llm_service.sessions['user2']) == 1


@pytest.mark.asyncio
async def test_history_cropping(llm_service):
    """验证对话历史裁剪逻辑（async 适配）。"""
    from config import LLM_MAX_HISTORY_TURNS
    session_id = 'test_crop'
    llm_service.sessions[session_id] = []

    # 填充超出上限的历史（每轮 2 条消息）
    for i in range(LLM_MAX_HISTORY_TURNS + 5):
        llm_service.sessions[session_id].append({'role': 'user', 'content': f'msg {i}'})
        llm_service.sessions[session_id].append({'role': 'assistant', 'content': f'reply {i}'})

    current_len = len(llm_service.sessions[session_id])
    assert current_len > LLM_MAX_HISTORY_TURNS * 2

    # Mock 路由 LLM（避免真实 API 调用）
    with patch.object(llm_service, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', 'test routing', '')  # v5: 三元组 (category, matched_signals, strategy_id)
        # Mock 流式 API 调用
        with patch.object(llm_service.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            # 构造一个空的流式响应
            mock_create.return_value = AsyncMock()
            mock_create.return_value.__aiter__.return_value = []

            gen = llm_service.stream_reply("new msg", {"label": "neutral"}, session_id)
            chunks = []
            async for chunk in gen:
                chunks.append(chunk)

    # 历史记录应该被裁剪到上限
    assert len(llm_service.sessions[session_id]) <= LLM_MAX_HISTORY_TURNS * 2


@pytest.mark.asyncio
async def test_routing_fallback_on_error(llm_service):
    """验证路由 LLM 异常时降级为 neutral，不中断对话。"""
    # Mock 路由 LLM 底层调用抛出异常（走 _route_category 内部 try/except）
    # self.client 被路由和生成共用——第一次 create 是路由，第二次是生成
    with patch.object(llm_service.client.chat.completions, 'create', new_callable=AsyncMock) as mock_api:
        # 第一次调用（路由）→ 抛异常
        # 第二次调用（生成）→ 返回空流
        empty_stream = AsyncMock()
        empty_stream.__aiter__.return_value = []
        mock_api.side_effect = [
            RuntimeError("路由服务不可用"),
            empty_stream,
        ]

        gen = llm_service.stream_reply("测试消息", {"label": "neutral"}, "test_fallback")
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)

    # 不应产生 error 事件（路由失败降级为 neutral 后正常完成）
    errors = [c for c in chunks if c.get('type') == 'error']
    assert len(errors) == 0
    # 应该正常产生 done 事件
    done_events = [c for c in chunks if c.get('type') == 'done']
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_crisis_skips_routing(llm_service):
    """验证危机关键词命中时跳过路由 LLM 调用。"""
    with patch.object(llm_service, '_route_category', new_callable=AsyncMock) as mock_route:
        # _route_category 返回三元组 (category, matched_signals, strategy_id)。
        # 这里以前写的是二元组，只因为该 mock 根本不会被调用才侥幸没炸——
        # 一旦哪天危机拦截失效，这个测试会以 unpack 报错而不是断言失败的形式
        # 挂掉，掩盖真正的问题。
        mock_route.return_value = ('neutral', '', '')
        with patch.object(llm_service.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = AsyncMock()
            mock_create.return_value.__aiter__.return_value = []

            gen = llm_service.stream_reply("我不想活了", {"label": "neutral"}, "test_crisis")
            chunks = []
            async for chunk in gen:
                chunks.append(chunk)

    # 路由 LLM 不应被调用（危机关键词直接拦截）
    mock_route.assert_not_called()
    # 所有 chunk 应标记 crisis: true
    for chunk in chunks:
        assert chunk.get('crisis') is True
    # done 事件应使用 crisis TTS 参数 + category='crisis'
    done = next(c for c in chunks if c.get('type') == 'done')
    assert done['category'] == 'crisis'
    assert done['tts_params']['style'] == 'gentle'
    assert done['tts_params']['speed'] == 0.82


@pytest.mark.asyncio
async def test_meta_event_precedes_deltas(llm_service):
    """
    meta 事件必须先于第一个 delta 到达。

    前端靠 meta 里的 tts_params 才能「凑够一句就合成一句」；如果这些字段只在
    done 里给，前端就只能等整段生成结束再出声，每轮多出好几秒静默。
    """
    with patch.object(llm_service, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('grief', '哀伤信号', 'externalize')
        with patch.object(llm_service.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _make_stream(['我在', '听着呢。'])
            chunks = [c async for c in llm_service.stream_reply(
                "我老伴走了三年了", {"label": "sad"}, "s_meta",
            )]

    types = [c['type'] for c in chunks]
    assert types[0] == 'meta', f"第一个事件应该是 meta，实际是 {types[0]}"
    assert 'delta' in types
    assert types.index('meta') < types.index('delta')

    meta = chunks[0]
    assert meta['category'] == 'grief'
    assert meta['tts_params']['speed'] == 0.82        # 哀伤 → 最缓
    assert meta['strategy_name'] == '外化对话'         # 策略中文名已解析好
    # done 仍然携带同样的字段（向后兼容）
    done = next(c for c in chunks if c['type'] == 'done')
    assert done['tts_params'] == meta['tts_params']
    assert done['category'] == meta['category']


@pytest.mark.asyncio
async def test_crisis_vigilance_persists_then_decays(llm_service):
    """
    危机之后的若干轮，即使不再命中危机关键词也维持警惕态（设计文档 §9.3）。

    这是本次修复的安全缺口之一：以前危机是逐轮重新判定的，下一句话没命中
    关键词就直接回到常规对话，等于危机一轮就翻篇。
    """
    from config import CRISIS_VIGILANCE_TURNS
    sid = 's_vigil'

    with patch.object(llm_service, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '', 'natural_followup')
        with patch.object(llm_service.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            # 第 1 轮：命中危机关键词
            mock_create.return_value = _make_stream(['我听到了。'])
            _ = [c async for c in llm_service.stream_reply(
                "我不想活了", {"label": "sad"}, sid)]
            assert llm_service.crisis_vigilance[sid] == CRISIS_VIGILANCE_TURNS

            # 之后 N 轮都是普通闲聊，警惕期应逐轮衰减但仍然生效
            for expected_after in range(CRISIS_VIGILANCE_TURNS - 1, -1, -1):
                assert llm_service._is_crisis_vigilant(sid) is True
                mock_create.return_value = _make_stream(['嗯。'])
                _ = [c async for c in llm_service.stream_reply(
                    "今天天气不错", {"label": "neutral"}, sid)]
                assert llm_service.crisis_vigilance[sid] == expected_after

                # 警惕段确实进了 system prompt，而不只是记了个状态
                sys_prompt = mock_create.call_args.kwargs['messages'][0]['content']
                assert '前几轮出现过让人担心的话' in sys_prompt

    # 衰减到 0 之后恢复常规对话
    assert llm_service._is_crisis_vigilant(sid) is False


class _StubMemory:
    """替身记忆服务，用来验证 LLMService 和记忆之间的接线。"""

    def __init__(self):
        self.observed: list = []
        self.folded: list = []

    def get_context(self, elder_id):
        return '【他提到过的人】\n- 建国（老伴）[已故]：走了三年'

    def get_summary(self, session_id):
        return '老人聊起了老伴建国，说他走了三年。'

    async def observe_turn(self, elder_id, user_text):
        self.observed.append((elder_id, user_text))
        return {}

    async def fold_into_summary(self, session_id, messages):
        self.folded.append(messages)
        return ''

    def reset_session(self, session_id):
        pass

    def close_session(self, elder_id, session_id):
        pass


@pytest.fixture
def llm_with_memory():
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        service = LLMService(memory_service=_StubMemory())
    return service


@pytest.mark.asyncio
async def test_memory_is_injected_into_system_prompt(llm_with_memory):
    """
    台账和摘要必须真的进到 system prompt——记下来却不注入等于没记。

    同时验证事实红线已经改写成「台账里的内容也可以用」：只加台账不改红线的话，
    模型会以为台账内容属于"对方没说过的事"，照样不敢引用。
    """
    svc = llm_with_memory
    with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('grief', '哀伤信号', 'externalize')
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _make_stream(['嗯。'])
            _ = [c async for c in svc.stream_reply(
                "我今天又想起他了", {"label": "sad"}, "s_mem", "elder_x")]

    sys_prompt = mock_create.call_args.kwargs['messages'][0]['content']
    assert '建国' in sys_prompt, "台账内容没进 system prompt"
    assert '老伴' in sys_prompt
    assert '老人聊起了老伴建国' in sys_prompt, "滚动摘要没进 system prompt"
    # 红线明确把台账列为可用来源
    assert '你能用的事实只有两个来源' in sys_prompt


@pytest.mark.asyncio
async def test_normal_turn_feeds_memory_but_crisis_turn_does_not(llm_with_memory):
    """
    普通轮次写入长程记忆；危机轮次不写。

    危机内容仍然留在对话历史里（下一轮需要这个语境），但不该沉淀成跨会话的
    永久记录，以后被回指出来。
    """
    svc = llm_with_memory
    with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '', 'natural_followup')
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _make_stream(['嗯。'])
            _ = [c async for c in svc.stream_reply(
                "今天吃了饺子", {"label": "neutral"}, "s_a", "elder_y")]
            await asyncio.sleep(0)   # 让后台任务跑起来

            mock_create.return_value = _make_stream(['我听到了。'])
            _ = [c async for c in svc.stream_reply(
                "我不想活了", {"label": "sad"}, "s_a", "elder_y")]
            await asyncio.sleep(0)

    observed_texts = [t for _, t in svc.memory.observed]
    assert "今天吃了饺子" in observed_texts
    assert "我不想活了" not in observed_texts, "危机内容不应写入长程记忆"


@pytest.mark.asyncio
async def test_dropped_history_is_folded_into_summary(llm_with_memory):
    """
    滑出历史窗口的消息必须进滚动摘要，否则一小时对话里前 55 分钟就真的没了。
    """
    from config import LLM_MAX_HISTORY_TURNS, MEMORY_SUMMARY_EVERY_N_MSGS
    svc = llm_with_memory
    sid = 's_fold'
    # 预填满历史，使后续轮次必然产生裁剪
    svc.sessions[sid] = []
    for i in range(LLM_MAX_HISTORY_TURNS * 2 + MEMORY_SUMMARY_EVERY_N_MSGS):
        svc.sessions[sid].append({'role': 'user', 'content': f'老人第{i}句'})
        svc.sessions[sid].append({'role': 'assistant', 'content': f'回复{i}'})

    with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '', 'natural_followup')
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _make_stream(['嗯。'])
            _ = [c async for c in svc.stream_reply(
                "新的一句", {"label": "neutral"}, sid, "elder_z")]
            await asyncio.sleep(0)

    assert svc.memory.folded, "被裁掉的历史没有交给摘要压缩"
    folded_contents = [m['content'] for batch in svc.memory.folded for m in batch]
    assert any('老人第0句' in c for c in folded_contents)


@pytest.mark.asyncio
async def test_strategy_effect_feedback_reaches_router(llm_service):
    """
    上一条策略的效果（由两轮之间的 valence 变化得出）必须传给路由。

    这是策略推进的闭环信号：没有它，路由每轮都在不知道上一步有没有起作用的
    情况下决定要不要往下走，分阶段干预就退化成了瞎猜。
    """
    sid = 's_effect'
    with patch.object(llm_service, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('anger', '愤怒信号', 'pause_breathe')
        with patch.object(llm_service.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            # 第 1 轮：valence 很低（生气）
            mock_create.return_value = _make_stream(['嗯。'])
            _ = [c async for c in llm_service.stream_reply(
                "他们太气人了", {"label": "angry", "valence": 0.10}, sid)]
            # 第 1 轮没有上一条策略可结算
            assert mock_route.call_args.kwargs.get('strategy_feedback', '') == ''

            # 第 2 轮：valence 明显回升 → 应判定为「好转」
            mock_create.return_value = _make_stream(['嗯。'])
            _ = [c async for c in llm_service.stream_reply(
                "唉，算了", {"label": "neutral", "valence": 0.50}, sid)]

    feedback = mock_route.call_args.kwargs['strategy_feedback']
    assert 'pause_breathe' in feedback
    assert '好转' in feedback
    # 效果也记进了策略统计
    assert llm_service.strategy_history[sid]['anger']['pause_breathe']['last_effect'] == '好转'


@pytest.mark.asyncio
async def test_strategy_stats_survive_a_long_conversation(llm_service):
    """
    一小时对话里同一类别会被访问几十次，早期用过的策略不能被挤出统计。

    以前存的是原始记录列表并按最近 8 条截断，30 轮之后开头用过什么就"忘了"，
    路由于是又从第一条策略重新做一遍。现在按 strategy_id 聚合，条目数天然
    受限于该类别的策略条数。
    """
    sid = 's_long'
    emotion = {"label": "sad", "valence": 0.2}
    for i in range(40):
        llm_service._record_strategy_use(
            sid, 'depression',
            'identify_negative_thoughts' if i == 0 else 'cognitive_reframe',
            emotion,
        )

    stats = llm_service.strategy_history[sid]['depression']
    # 第 1 轮用的那条 40 轮之后依然在册
    assert 'identify_negative_thoughts' in stats
    assert stats['identify_negative_thoughts']['count'] == 1
    assert stats['cognitive_reframe']['count'] == 39

    rendered = llm_service._format_used_strategies(sid)
    assert 'identify_negative_thoughts×1' in rendered
    assert 'cognitive_reframe×39' in rendered


@pytest.mark.asyncio
async def test_closing_reviews_the_session(llm_with_memory):
    """
    收束告别要基于本次会话的摘要做具体回顾，而不是一句空泛的客套。

    以前"结束对话"就是 2.5 秒后清屏——把一段哀伤叙事打开之后这样收场，
    等于把刚敞开心扉的人晾在那儿。
    """
    svc = llm_with_memory
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as mock_create:
        mock_create.return_value = _make_stream(['今天听你说了不少。'])
        chunks = [c async for c in svc.stream_closing('s_close', 'elder_c')]

    sys_prompt = mock_create.call_args.kwargs['messages'][0]['content']
    assert '老人聊起了老伴建国' in sys_prompt, "收尾没有用上本次会话的摘要"
    assert '不要提问' in sys_prompt
    assert '不要开新话题' in sys_prompt

    types = [c['type'] for c in chunks]
    assert types[0] == 'meta'
    assert types[-1] == 'done'
    assert chunks[-1]['category'] == 'closing'


@pytest.mark.asyncio
async def test_closing_falls_back_when_generation_fails(llm_with_memory):
    """生成失败也必须有一句告别——不能因为 API 挂了就无声消失。"""
    svc = llm_with_memory
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as mock_create:
        mock_create.side_effect = RuntimeError('API 挂了')
        chunks = [c async for c in svc.stream_closing('s_close2', 'elder_c')]

    done = next(c for c in chunks if c['type'] == 'done')
    assert done['full_text'].strip(), "生成失败时没有任何告别内容"
    assert any(c['type'] == 'delta' for c in chunks)


def test_truncate_last_reply_keeps_only_what_was_heard(llm_service):
    """
    被打断时，历史里那条回复要截断成实际播出去的部分。

    不截断的话模型以为整段说完了，下一轮可能出现「我刚才跟你说的那个……」，
    而老人根本没听到后半截。
    """
    sid = 's_trunc'
    llm_service.sessions[sid] = [
        {'role': 'user', 'content': '我今天有点累'},
        {'role': 'assistant', 'content': '嗯，听得出来。今天是不是没歇好？要不咱们说说？'},
    ]

    changed = llm_service.truncate_last_reply(sid, '嗯，听得出来。')
    assert changed is True
    assert llm_service.sessions[sid][-1]['content'] == '嗯，听得出来。'
    assert len(llm_service.sessions[sid]) == 2   # 用户那条不动


def test_truncate_removes_reply_when_nothing_was_heard(llm_service):
    """一个字都没播出去就被打断 → 整条回复从历史里移除。"""
    sid = 's_trunc2'
    llm_service.sessions[sid] = [
        {'role': 'user', 'content': '我今天有点累'},
        {'role': 'assistant', 'content': '嗯，听得出来。'},
    ]
    assert llm_service.truncate_last_reply(sid, '') is True
    assert len(llm_service.sessions[sid]) == 1
    assert llm_service.sessions[sid][-1]['role'] == 'user'


def test_truncate_is_noop_when_fully_spoken_or_nothing_to_cut(llm_service):
    """全部播完、或历史里最后一条不是回复时，不该乱改。"""
    sid = 's_trunc3'
    full = '嗯，听得出来。'
    llm_service.sessions[sid] = [
        {'role': 'user', 'content': '我今天有点累'},
        {'role': 'assistant', 'content': full},
    ]
    assert llm_service.truncate_last_reply(sid, full) is False
    assert llm_service.sessions[sid][-1]['content'] == full

    # 最后一条是用户消息（回复还没生成）
    llm_service.sessions[sid].pop()
    assert llm_service.truncate_last_reply(sid, '随便什么') is False
    # 会话根本不存在
    assert llm_service.truncate_last_reply('不存在的会话', '啥') is False


def test_truncate_resets_question_streak_when_question_cut_off(llm_service):
    """
    以问句结尾的回复被截断掉问句部分后，连续提问计数要跟着清零。

    否则明明那个问题老人没听到，系统却记着"已经连问三轮了"，
    接下来该问的时候反而不问了。
    """
    sid = 's_trunc4'
    llm_service.sessions[sid] = [
        {'role': 'user', 'content': '还行'},
        {'role': 'assistant', 'content': '嗯。今天过得咋样？'},
    ]
    llm_service._note_reply_shape(sid, '嗯。今天过得咋样？')
    assert llm_service._get_session_meta(sid)['consecutive_questions'] == 1

    llm_service.truncate_last_reply(sid, '嗯。')
    assert llm_service._get_session_meta(sid)['consecutive_questions'] == 0


def test_category_tts_params(llm_service):
    """验证心理类别 → TTS 参数映射（语义驱动）。"""
    # 哀伤/抑郁 → 最缓
    assert llm_service._get_tts_params_by_category('grief', False)['speed'] == 0.82
    assert llm_service._get_tts_params_by_category('depression', False)['style'] == 'gentle'
    # 积极 → 明快
    assert llm_service._get_tts_params_by_category('positive', False)['speed'] == 1.05
    assert llm_service._get_tts_params_by_category('positive', False)['style'] == 'cheerful'
    # 中性 → 正常
    assert llm_service._get_tts_params_by_category('neutral', False)['speed'] == 1.00
    # 危机 → 最缓
    assert llm_service._get_tts_params_by_category('neutral', True)['speed'] == 0.82
    # 未知类别 → 降级 neutral
    assert llm_service._get_tts_params_by_category('unknown', False)['speed'] == 1.00
