"""端点层：护栏在服务端生效，前端只是触发器。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))


@pytest.fixture
def svc(tmp_path):
    from services.llm_service import LLMService
    from services.profile_service import ProfileService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch('services.profile_service.AsyncOpenAI'):
            with patch.object(LLMService, '_write_event', return_value={}):
                yield LLMService(profile_service=ProfileService(storage_dir=str(tmp_path)))


def test_guard_blocks_during_crisis_vigilance(svc):
    svc._enter_crisis_vigilance('s1')
    ok, why = svc.can_speak_proactively('s1', 'e1')
    assert not ok
    assert why == 'crisis_vigilant'


def test_guard_allows_normally(svc):
    with patch('services.proactive.in_quiet_hours', return_value=False):
        ok, _ = svc.can_speak_proactively('s1', 'e1')
    assert ok


def test_no_answer_streak_blocks(svc):
    with patch('services.proactive.in_quiet_hours', return_value=False):
        svc.note_proactive_no_answer('e1')
        svc.note_proactive_no_answer('e1')
        ok, why = svc.can_speak_proactively('s1', 'e1')
    assert not ok
    assert why == 'no_answer_giveup'


def test_answered_resets_streak(svc):
    with patch('services.proactive.in_quiet_hours', return_value=False):
        svc.note_proactive_no_answer('e1')
        svc.note_proactive_answered('e1')
        svc.note_proactive_no_answer('e1')
        ok, _ = svc.can_speak_proactively('s1', 'e1')
    assert ok


@pytest.mark.asyncio
async def test_endpoint_returns_blocked_event_when_guard_refuses(svc):
    """被护栏挡住时返回一个 blocked 事件，前端据此安静收场。"""
    import routers.sse_llm as mod
    mod.llm_service = svc
    svc._enter_crisis_vigilance('s1')

    resp = await mod.stream_proactive_endpoint(session_id='s1', elder_id='e1',
                                               trigger='scheduled')
    body = b''.join([chunk async for chunk in resp.body_iterator])
    payload = json.loads(body.decode().removeprefix('data: ').strip())
    assert payload['type'] == 'blocked'
    assert payload['reason'] == 'crisis_vigilant'


@pytest.mark.asyncio
async def test_endpoint_streams_when_allowed(svc):
    import routers.sse_llm as mod
    mod.llm_service = svc

    async def gen():
        yield MagicMock(choices=[MagicMock(delta=MagicMock(content='天不错啊。'))])
    stream = AsyncMock()
    stream.__aiter__ = lambda self: gen()

    with patch('services.proactive.in_quiet_hours', return_value=False):
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as api:
            api.return_value = stream
            resp = await mod.stream_proactive_endpoint(
                session_id='s1', elder_id='e1', trigger='scheduled')
            body = b''.join([c async for c in resp.body_iterator]).decode()

    assert '"type": "meta"' in body
    assert '天不错啊。' in body


@pytest.mark.asyncio
async def test_outcome_endpoint_records(svc):
    import routers.sse_llm as mod
    mod.llm_service = svc
    await mod.proactive_outcome(elder_id='e1', answered=False)
    await mod.proactive_outcome(elder_id='e1', answered=False)
    with patch('services.proactive.in_quiet_hours', return_value=False):
        ok, why = svc.can_speak_proactively('s1', 'e1')
    assert not ok and why == 'no_answer_giveup'
