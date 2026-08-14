"""听力状况 → TTS 语速。画像里唯一的闭环。"""
import pytest
from unittest.mock import MagicMock, patch

from services.profile_service import mark_filled


@pytest.fixture
def svc(tmp_path):
    from services.llm_service import LLMService
    from services.profile_service import ProfileService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch('services.profile_service.AsyncOpenAI'):
            yield LLMService(profile_service=ProfileService(storage_dir=str(tmp_path)))


def test_unknown_hearing_uses_baseline(svc):
    p = svc._get_tts_params_by_category('neutral', False, elder_id='e1')
    assert p['speed'] == 1.00


def test_hard_of_hearing_slows_down(svc):
    prof = svc.profile.get_profile('e1')
    mark_filled(prof, 'sensory_hearing', '耳背，得大声说')
    p = svc._get_tts_params_by_category('neutral', False, elder_id='e1')
    assert p['speed'] < 1.00


def test_normal_hearing_does_not_slow_down(svc):
    prof = svc.profile.get_profile('e1')
    mark_filled(prof, 'sensory_hearing', '听得挺清楚')
    p = svc._get_tts_params_by_category('neutral', False, elder_id='e1')
    assert p['speed'] == 1.00


def test_adjustment_stacks_on_category_params(svc):
    """不是覆盖类别参数，是在它基础上再放慢。"""
    prof = svc.profile.get_profile('e1')
    mark_filled(prof, 'sensory_hearing', '耳背')
    grief = svc._get_tts_params_by_category('grief', False, elder_id='e1')
    assert grief['speed'] < 0.82
    assert grief['style'] == 'gentle', '风格仍由类别决定'


def test_speed_never_goes_below_floor(svc):
    """再慢也得像正常说话，不能慢到诡异。"""
    prof = svc.profile.get_profile('e1')
    mark_filled(prof, 'sensory_hearing', '耳背得厉害')
    p = svc._get_tts_params_by_category('depression', False, elder_id='e1')
    assert p['speed'] >= 0.70


def test_no_elder_id_returns_baseline(svc):
    p = svc._get_tts_params_by_category('neutral', False)
    assert p['speed'] == 1.00


def test_no_profile_service_is_safe():
    from services.llm_service import LLMService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        svc = LLMService(profile_service=None)
        assert svc._get_tts_params_by_category('neutral', False, elder_id='e1')['speed'] == 1.00
