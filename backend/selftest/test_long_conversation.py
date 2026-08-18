"""
长对话回放测试。

这个文件针对的是最初那个问题：「一次对话可能持续一个小时，现在的机制能不能
前后连贯、事实一致地完成？」

改造之前的答案是不能——对话历史只有 6 轮（约 3~5 分钟），第 40 分钟的模型对
第 5 分钟说过的话一无所知。下面用脚本化的 120 轮对话把这件事测出来：不看
实现细节，只看「第 5 轮提到的人，第 100 轮还记不记得」这种最终效果。

两个 LLM（路由 DeepSeek、生成 Qwen）都被 mock 掉，测的是我们自己的状态机和
prompt 组装，不依赖网络。
"""

import sys
import os
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_service import LLMService
from services.memory_service import MemoryService

SID = 'long_session'
ELDER = 'long_elder'
TOTAL_TURNS = 120
FACT_TURN = 5          # 在第几轮提到「桂芬」
CHECK_TURN = 100       # 到第几轮时检查还记不记得

# 故意选一个不会出现在任何 prompt 模板文案里的名字。
# 第一版这里用的是「建国」，而 templates.py 的举例里正好也有「建国」，
# 于是断言匹配到的是模板的固定文案、不是真正的记忆——测试看着过了其实什么
# 都没验证到。下面这条断言把这个坑焊死。
PERSON = '桂芬'


def test_person_name_is_not_in_any_prompt_template():
    """守卫断言：换名字的人如果不小心撞上模板文案，这里会先炸。"""
    from prompts import templates
    from pathlib import Path
    source = Path(templates.__file__).read_text(encoding='utf-8')
    assert PERSON not in source, (
        f"「{PERSON}」出现在 prompt 模板里了，长对话测试的断言会变成假阳性"
    )


def _make_stream(texts):
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


async def _drain(svc):
    """等所有后台记忆任务跑完，让断言是确定性的。"""
    while svc._bg_tasks:
        await asyncio.gather(*list(svc._bg_tasks), return_exceptions=True)


def _build_service(tmp_path):
    """装一套真的记忆服务（只 mock 掉它内部的两次 LLM 调用）。"""
    memory = MemoryService(storage_dir=str(tmp_path))

    async def fake_extract(user_text):
        if '桂芬' in user_text:
            return {
                'people': [{'name': '桂芬', 'relation': '老伴',
                            'status': '已故', 'note': '走了三年'}],
                'events': [], 'preferences': [],
            }
        return {'people': [], 'events': [], 'preferences': []}

    async def fake_summarize(conversation_text, previous):
        # 摘要只要能累积、能被截断就够，不需要真的调模型
        return (previous + ' 又聊了些日常琐事。').strip()[:400]

    extract_patch = patch.object(memory, '_extract_facts', new_callable=AsyncMock)
    summarize_patch = patch.object(memory, '_summarize', new_callable=AsyncMock)
    m_extract = extract_patch.start()
    m_summarize = summarize_patch.start()
    m_extract.side_effect = fake_extract
    m_summarize.side_effect = fake_summarize

    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        svc = LLMService(memory_service=memory)

    return svc, [extract_patch, summarize_patch]


@pytest.mark.asyncio
async def test_early_fact_still_known_at_turn_100(tmp_path):
    """
    第 5 轮提到的人物，到第 100 轮仍然在注入生成模型的 prompt 里。

    这是整套改造要解决的核心问题。没有长程记忆时，「桂芬」在大约第 11 轮就会
    随着历史窗口滑出去，之后模型要么反问「桂芬是谁」（老人会觉得没被倾听），
    要么顺着语气编（违反事实红线）。
    """
    svc, patches = _build_service(tmp_path)
    try:
        with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
            mock_route.return_value = ('neutral', '', 'natural_followup', '')
            with patch.object(svc.client.chat.completions, 'create',
                              new_callable=AsyncMock) as mock_create:
                prompt_at_check = None
                for turn in range(TOTAL_TURNS):
                    mock_create.return_value = _make_stream(['嗯，我听着呢。'])
                    text = ('我老伴桂芬走了三年了' if turn == FACT_TURN
                            else f'今天还有第{turn}件小事')
                    _ = [c async for c in svc.stream_reply(
                        text, {'label': 'neutral', 'valence': 0.5}, SID, ELDER)]
                    await _drain(svc)

                    if turn == CHECK_TURN:
                        prompt_at_check = mock_create.call_args.kwargs['messages'][0]['content']
    finally:
        for p in patches:
            p.stop()

    assert prompt_at_check is not None
    assert '桂芬' in prompt_at_check, "第 100 轮已经不记得第 5 轮提到的人了"
    assert '老伴' in prompt_at_check
    assert '走了三年' in prompt_at_check

    # 而且这条记忆是落了盘的，跨会话也还在
    reloaded = MemoryService(storage_dir=str(tmp_path))
    assert '桂芬' in reloaded.get_context(ELDER)


@pytest.mark.asyncio
async def test_history_window_alone_would_have_lost_it(tmp_path):
    """
    对照：同样 120 轮，关掉记忆之后第 100 轮的 prompt 里就没有「桂芬」了。

    这条用来确认上面那个测试测的确实是长程记忆的功劳，而不是因为对话历史
    窗口碰巧还留着——避免测试通过了但其实什么都没验证到。
    """
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        svc = LLMService(memory_service=None)   # 关掉记忆

    with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '', 'natural_followup', '')
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            prompt_at_check = None
            for turn in range(CHECK_TURN + 1):
                mock_create.return_value = _make_stream(['嗯。'])
                text = ('我老伴桂芬走了三年了' if turn == FACT_TURN
                        else f'今天还有第{turn}件小事')
                _ = [c async for c in svc.stream_reply(
                    text, {'label': 'neutral', 'valence': 0.5}, SID, ELDER)]
                if turn == CHECK_TURN:
                    msgs = mock_create.call_args.kwargs['messages']
                    prompt_at_check = ' '.join(m['content'] for m in msgs)

    assert prompt_at_check is not None
    assert '桂芬' not in prompt_at_check


@pytest.mark.asyncio
async def test_rolling_summary_accumulates_over_long_run(tmp_path):
    """滑出历史窗口的内容会被压缩进滚动摘要，而不是凭空消失。"""
    svc, patches = _build_service(tmp_path)
    try:
        with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
            mock_route.return_value = ('neutral', '', 'natural_followup', '')
            with patch.object(svc.client.chat.completions, 'create',
                              new_callable=AsyncMock) as mock_create:
                for turn in range(40):
                    mock_create.return_value = _make_stream(['嗯。'])
                    _ = [c async for c in svc.stream_reply(
                        f'第{turn}句', {'label': 'neutral', 'valence': 0.5}, SID, ELDER)]
                    await _drain(svc)

        summary = svc.memory.get_summary(SID)
    finally:
        for p in patches:
            p.stop()

    assert summary, "长对话跑完之后滚动摘要仍然是空的"
    from config import MEMORY_SUMMARY_MAX_CHARS
    assert len(summary) <= MEMORY_SUMMARY_MAX_CHARS


@pytest.mark.asyncio
async def test_questions_get_restrained_in_a_long_run(tmp_path):
    """
    连续以问句收尾达到阈值后，prompt 会要求这一轮别再提问。

    CARE 的 E 步骤原本几乎每轮必做，一小时下来是 100 多个开放问题——
    那是审讯不是陪伴。
    """
    from config import MAX_CONSECUTIVE_QUESTIONS

    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        svc = LLMService(memory_service=None)

    with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '', 'natural_followup', '')
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            # 每一轮回复都以问句结尾
            for _ in range(MAX_CONSECUTIVE_QUESTIONS):
                mock_create.return_value = _make_stream(['今天过得咋样？'])
                _ = [c async for c in svc.stream_reply(
                    '还行', {'label': 'neutral', 'valence': 0.5}, SID, ELDER)]

            # 下一轮的 prompt 应当要求跳过 E 步骤
            mock_create.return_value = _make_stream(['嗯。'])
            _ = [c async for c in svc.stream_reply(
                '还行', {'label': 'neutral', 'valence': 0.5}, SID, ELDER)]
            sys_prompt = mock_create.call_args.kwargs['messages'][0]['content']

    assert '不要再提问' in sys_prompt


@pytest.mark.asyncio
async def test_phase_reaches_closing_after_long_session(tmp_path):
    """聊够久之后进入收束阶段，prompt 转为往收尾引导。"""
    from config import SESSION_CLOSING_AFTER_MIN, SESSION_OPENING_TURNS

    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        svc = LLMService(memory_service=None)

    # 刚开始是暖场
    assert svc.get_phase(SID) == 'opening'

    svc._get_session_meta(SID)['turn_count'] = SESSION_OPENING_TURNS
    assert svc.get_phase(SID) == 'deepening'

    # 把开始时间往前拨，模拟已经聊了很久
    svc._get_session_meta(SID)['started_at'] = (
        datetime.now(timezone.utc) - timedelta(minutes=SESSION_CLOSING_AFTER_MIN + 1)
    )
    assert svc.get_phase(SID) == 'closing'

    with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '', 'natural_followup', '')
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _make_stream(['嗯。'])
            _ = [c async for c in svc.stream_reply(
                '是啊', {'label': 'neutral', 'valence': 0.5}, SID, ELDER)]
            sys_prompt = mock_create.call_args.kwargs['messages'][0]['content']

    assert '慢慢往收尾上引' in sys_prompt
