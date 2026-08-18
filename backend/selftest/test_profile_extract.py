"""画像抽取。抽取失败绝不能影响对话。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.profile_service import ProfileService, PROFILE_EXTRACT_SYSTEM_PROMPT


@pytest.fixture
def svc(tmp_path):
    with patch('services.profile_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        yield ProfileService(storage_dir=str(tmp_path))


def _reply(payload: dict):
    return MagicMock(choices=[MagicMock(message=MagicMock(
        content=json.dumps(payload, ensure_ascii=False)))])


def test_prompt_lists_only_askable_slots():
    assert 'hometown' in PROFILE_EXTRACT_SYSTEM_PROMPT
    assert 'talkativeness' not in PROFILE_EXTRACT_SYSTEM_PROMPT
    assert '不要推测' in PROFILE_EXTRACT_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_extract_fills_slots(svc):
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _reply({'hometown': '河北保定', 'occupation': '小学老师'})
        got = await svc.observe_turn('e1', '我老家保定的，以前教小学')

    assert got['hometown'] == '河北保定'
    p = svc.get_profile('e1')
    assert p['slots']['hometown']['value'] == '河北保定'
    assert p['slots']['hometown']['status'] == 'filled'
    assert p['slots']['hometown']['evidence'], '来源要留痕，支撑将来的导出'


@pytest.mark.asyncio
async def test_extract_routes_birth_year_through_validator(svc):
    """抽到年龄数字要被拒（设计文档 §3.6）。"""
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _reply({'birth_year': '83'})
        await svc.observe_turn('e1', '我今年八十三了')
    assert svc.get_profile('e1')['slots']['birth_year']['status'] == 'unknown'

    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _reply({'birth_year': '1943'})
        await svc.observe_turn('e1', '我 43 年生的')
    assert svc.get_profile('e1')['slots']['birth_year']['value'] == '1943'


@pytest.mark.asyncio
async def test_extract_ignores_unknown_and_non_askable_keys(svc):
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _reply({
            'favorite_color': '蓝色',
            'talkativeness': '话多',
            'location': '北京',
        })
        got = await svc.observe_turn('e1', '随便说说')
    assert got == {}


@pytest.mark.asyncio
async def test_extract_failure_is_swallowed(svc):
    """抽取失败只记 warning，不能抛到调用方（设计文档 §9）。"""
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.side_effect = RuntimeError('api down')
        got = await svc.observe_turn('e1', '我老家保定的')
    assert got == {}


@pytest.mark.asyncio
async def test_extract_skips_blank_text(svc):
    assert await svc.observe_turn('e1', '   ') == {}


@pytest.mark.asyncio
async def test_extract_persists_to_disk(svc, tmp_path):
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _reply({'hometown': '保定'})
        await svc.observe_turn('e1', '我老家保定的')

    fresh = ProfileService(storage_dir=str(tmp_path))
    assert fresh.get_profile('e1')['slots']['hometown']['value'] == '保定'
