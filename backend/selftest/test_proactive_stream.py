"""主动开口的 prompt 与流式输出。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from prompts.templates import build_proactive_prompt


def test_prompt_forbids_leading_question():
    """设计文档 §6.2：第一句不能是问句，上来就问就是查户口。"""
    p = build_proactive_prompt('张阿姨', 'scheduled')
    assert '第一句' in p
    assert '不要用问句开头' in p


def test_prompt_uses_address():
    p = build_proactive_prompt('王老师', 'scheduled')
    assert '王老师' in p


def test_prompt_with_default_address_says_do_not_invent():
    """称呼未知时兜底「您」，且明确禁止编一个（设计文档 §3.5）。"""
    p = build_proactive_prompt('您', 'scheduled')
    assert '您' in p
    assert '不要自己编' in p


def test_silence_trigger_differs_from_scheduled():
    """沉默唤起是在对话中间，不该再打一次招呼。"""
    a = build_proactive_prompt('张阿姨', 'silence')
    b = build_proactive_prompt('张阿姨', 'scheduled')
    assert a != b
    assert '刚才安静了一会儿' in a


def test_prompt_embeds_elicitation_block():
    p = build_proactive_prompt('张阿姨', 'scheduled', elicitation_block='顺便聊聊老家')
    assert '顺便聊聊老家' in p


@pytest.fixture
def svc(tmp_path):
    from services.llm_service import LLMService
    from services.profile_service import ProfileService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch('services.profile_service.AsyncOpenAI'):
            with patch.object(LLMService, '_write_event', return_value={}):
                yield LLMService(profile_service=ProfileService(storage_dir=str(tmp_path)))


def _stream(chunks):
    async def gen():
        for c in chunks:
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=c))])
    m = AsyncMock()
    m.__aiter__ = lambda self: gen()
    return m


@pytest.mark.asyncio
async def test_stream_proactive_emits_meta_then_done(svc):
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _stream(['外头天不错啊。'])
        events = [e async for e in svc.stream_proactive('s1', 'e1', 'scheduled')]

    assert events[0]['type'] == 'meta'
    assert events[0]['category'] == 'proactive'
    assert events[0]['tts_params']['speed'] == 1.00
    assert events[-1]['type'] == 'done'
    assert events[-1]['full_text'] == '外头天不错啊。'


@pytest.mark.asyncio
async def test_proactive_reply_enters_history(svc):
    """主动说的话必须进历史，否则老人回应时模型不知道自己刚说了什么。"""
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _stream(['外头天不错啊。'])
        async for _ in svc.stream_proactive('s1', 'e1', 'scheduled'):
            pass
    assert svc.sessions['s1'][-1] == {'role': 'assistant', 'content': '外头天不错啊。'}


@pytest.mark.asyncio
async def test_proactive_failure_is_silent_no_fallback_text(svc):
    """设计文档 §9：主动开口失败静默放弃，不重试、不兜底说一句。

    和 closing 相反——closing 失败必须有兜底（不能把人晾在那儿），
    proactive 失败必须没有兜底（不能因为失败就反复出声）。
    """
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.side_effect = RuntimeError('api down')
        events = [e async for e in svc.stream_proactive('s1', 'e1', 'scheduled')]

    assert not any(e['type'] == 'delta' for e in events)
    assert events[-1]['type'] == 'done'
    assert events[-1]['full_text'] == ''


@pytest.mark.asyncio
async def test_proactive_marks_address_asked(svc):
    """称呼还没采到时，主动招呼顺带问，并记进画像。"""
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _stream(['外头天不错。我该怎么称呼您呀？'])
        async for _ in svc.stream_proactive('s1', 'e1', 'scheduled'):
            pass
    assert svc.profile.get_profile('e1')['slots']['address']['ask_count'] == 1


@pytest.mark.asyncio
async def test_proactive_reuses_question_throttle(svc):
    """必须复用现有问句节流器 _should_restrain_questions()，不能另起一套计数。

    沉默唤起（trigger='silence'）发生在对话中间：如果前几轮 AI 已经连续问了
    好几个问题，节流器会判定「该收一收了」。这个状态必须被主动开口的采集
    规划尊重——否则沉默唤起可以绕开节流器，在刚追问了一串问题之后又借着
    采集问题接着问，正是节流器要防的事。
    """
    from config import MAX_CONSECUTIVE_QUESTIONS

    meta = svc._get_session_meta('s1')
    meta['consecutive_questions'] = MAX_CONSECUTIVE_QUESTIONS
    assert svc._should_restrain_questions('s1') is True

    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _stream(['外头天不错啊。'])
        async for _ in svc.stream_proactive('s1', 'e1', 'silence'):
            pass

    # 节流生效时，采集规划器应返回 MODE_NONE——不该顺带问称呼（或任何字段）。
    assert svc.profile.get_profile('e1')['slots']['address']['ask_count'] == 0


@pytest.mark.asyncio
async def test_proactive_silence_respects_sensitive_category(svc):
    """沉默唤起必须用会话真实的 last_category，不能硬编码 'neutral'。

    沉默唤起发生在对话中间——如果上一轮判定的类别是敏感类别（比如
    grief），说明老人可能正处在一段敏感叙事的停顿里。安全窗口门槛
    （category in ('neutral','positive')）必须挡住这种情况下的主动
    起话头，否则沉默唤起会在敏感叙事中间插进一句不相关的采集提问。
    """
    svc.last_category['s1'] = 'grief'

    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _stream(['外头天不错啊。我该怎么称呼您呀？'])
        async for _ in svc.stream_proactive('s1', 'e1', 'silence'):
            pass

    # 敏感类别下，安全窗口门槛应挡住采集（包括称呼）。
    assert svc.profile.get_profile('e1')['slots']['address']['ask_count'] == 0


@pytest.mark.asyncio
async def test_proactive_silence_respects_closing_phase(svc):
    """沉默唤起必须用会话真实的 phase，不能硬编码 'opening'。

    如果这次沉默发生在会话已经进入收尾阶段（聊了很久），安全窗口门槛
    （phase != 'closing'）必须挡住主动起话头——这时候不该再开一个新的
    采集话题。
    """
    from datetime import datetime, timedelta, timezone
    from config import SESSION_CLOSING_AFTER_MIN

    meta = svc._get_session_meta('s1')
    meta['started_at'] = datetime.now(timezone.utc) - timedelta(
        minutes=SESSION_CLOSING_AFTER_MIN + 1
    )
    assert svc.get_phase('s1') == 'closing'

    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _stream(['外头天不错啊。我该怎么称呼您呀？'])
        async for _ in svc.stream_proactive('s1', 'e1', 'silence'):
            pass

    # 收尾阶段下，安全窗口门槛应挡住采集（包括称呼）。
    assert svc.profile.get_profile('e1')['slots']['address']['ask_count'] == 0
