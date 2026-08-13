"""采集指令怎么进到 prompt 里，以及会话级计数器怎么推进。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from prompts.templates import build_elicitation_block, build_normal_prompt
from services.elicitation import MODE_NONE, MODE_FOLLOW_UP, MODE_OPEN_TOPIC

EMOTION = {'label': 'neutral', 'label_zh': '平静', 'score': 0.9,
           'valence': 0.5, 'arousal': 0.2, 'trend': '首次对话'}


def test_block_none_tells_model_to_just_chat():
    text = build_elicitation_block(MODE_NONE, '', False)
    assert '正常聊' in text


def test_follow_up_block_forbids_changing_topic():
    text = build_elicitation_block(MODE_FOLLOW_UP, 'sleep', False)
    assert '睡得好不好' in text, '必须用中文说法，不能把英文字段名念出来'
    assert '不要转移话题' in text


def test_open_topic_block_uses_chinese_name():
    text = build_elicitation_block(MODE_OPEN_TOPIC, 'hometown', False)
    assert '老家' in text
    assert 'hometown' not in text


def test_stale_block_says_confirm_not_ask():
    """设计文档 §5.5：确认已知信息是亲近的表现，重新提问是疏远的表现。"""
    text = build_elicitation_block(MODE_OPEN_TOPIC, 'hobbies_current', True)
    assert '确认' in text
    assert '以前记过' in text


def test_address_block_is_natural_not_interrogative():
    text = build_elicitation_block(MODE_OPEN_TOPIC, 'address', False)
    assert '称呼' in text


def test_normal_prompt_embeds_elicitation_block():
    block = build_elicitation_block(MODE_OPEN_TOPIC, 'hometown', False)
    prompt = build_normal_prompt('neutral', EMOTION, elicitation_block=block)
    assert '老家' in prompt


def test_normal_prompt_without_block_still_builds():
    """默认空串，老调用方不受影响。"""
    prompt = build_normal_prompt('neutral', EMOTION)
    assert '蘅小年' in prompt


@pytest.fixture
def svc(tmp_path):
    from services.llm_service import LLMService
    from services.profile_service import ProfileService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
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
async def test_first_turn_asks_address_and_marks_it(svc):
    """第一次会话开场就问称呼，且记进画像（设计文档 §3.5）。"""
    with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '', 'natural_followup', '')
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _stream(['你好啊。'])
            async for _ in svc.stream_reply('你好', EMOTION, 's1', 'e1'):
                pass

    profile = svc.profile.get_profile('e1')
    assert profile['slots']['address']['ask_count'] == 1
    assert svc._get_session_meta('s1')['address_asked'] is True


@pytest.mark.asyncio
async def test_address_not_reasked_next_turn(svc):
    with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '', 'natural_followup', '')
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _stream(['嗯。'])
            for _ in range(3):
                mock_create.return_value = _stream(['嗯。'])
                async for _ in svc.stream_reply('随便说说', EMOTION, 's1', 'e1'):
                    pass

    assert svc.profile.get_profile('e1')['slots']['address']['ask_count'] == 1


@pytest.mark.asyncio
async def test_crisis_turn_never_elicits(svc):
    """危机轮两种采集都硬禁止。"""
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as mock_create:
        mock_create.return_value = _stream(['我听到了。'])
        async for _ in svc.stream_reply('我不想活了', EMOTION, 's2', 'e2'):
            pass

    profile = svc.profile.get_profile('e2')
    assert all(s['ask_count'] == 0 for s in profile['slots'].values())


@pytest.mark.asyncio
async def test_service_works_without_profile_service():
    """画像是增强能力，没有它对话照常（和 memory 一样的原则）。"""
    from services.llm_service import LLMService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        svc = LLMService(profile_service=None)
        with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
            mock_route.return_value = ('neutral', '', 'natural_followup', '')
            with patch.object(svc.client.chat.completions, 'create',
                              new_callable=AsyncMock) as mock_create:
                mock_create.return_value = _stream(['嗯。'])
                events = [e async for e in svc.stream_reply('你好', EMOTION, 's3', 'e3')]
    assert any(e['type'] == 'done' for e in events)
