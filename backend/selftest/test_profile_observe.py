"""观察类字段：永远不问，从对话行为统计。"""
import pytest
from unittest.mock import MagicMock, patch

from services.profile_service import ProfileService, STATUS_FILLED, STATUS_UNKNOWN


@pytest.fixture
def svc(tmp_path):
    with patch('services.profile_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        yield ProfileService(storage_dir=str(tmp_path))


def _feed(svc, n, text='还行吧', category='neutral', asked=False):
    for _ in range(n):
        svc.observe_behavior('e1', text, category, asked)


def test_below_min_sample_stays_unknown(svc):
    """设计文档 §3.2：样本不足时宁可留空。"""
    _feed(svc, 19)
    p = svc.get_profile('e1')
    assert p['slots']['talkativeness']['status'] == STATUS_UNKNOWN


def test_talkativeness_short_answers(svc):
    _feed(svc, 20, text='嗯')
    slot = svc.get_profile('e1')['slots']['talkativeness']
    assert slot['status'] == STATUS_FILLED
    assert '话少' in slot['value']
    assert slot['source'] == 'observed'


def test_talkativeness_long_answers(svc):
    _feed(svc, 20, text='那可说来话长了，' * 8)
    assert '话多' in svc.get_profile('e1')['slots']['talkativeness']['value']


def test_emotional_baseline_needs_more_samples(svc):
    _feed(svc, 25, category='depression')
    assert svc.get_profile('e1')['slots']['emotional_baseline']['status'] == STATUS_UNKNOWN
    _feed(svc, 5, category='depression')
    slot = svc.get_profile('e1')['slots']['emotional_baseline']
    assert slot['status'] == STATUS_FILLED
    assert '抑郁' in slot['value']


def test_emotional_baseline_ignores_neutral_only(svc):
    """全程中性说明没有明显底色，不该硬扣一顶帽子。"""
    _feed(svc, 40, category='neutral')
    assert svc.get_profile('e1')['slots']['emotional_baseline']['status'] == STATUS_UNKNOWN


def test_interaction_preference_prefers_talking_freely(svc):
    for _ in range(20):
        svc.observe_behavior('e1', '嗯', 'neutral', True)        # 被问之后话短
    for _ in range(20):
        svc.observe_behavior('e1', '那可有的说了，' * 6, 'neutral', False)  # 自己讲时话长
    slot = svc.get_profile('e1')['slots']['interaction_preference']
    assert slot['status'] == STATUS_FILLED
    assert '自己讲' in slot['value']


def test_observations_persist(svc, tmp_path):
    _feed(svc, 20, text='嗯')
    fresh = ProfileService(storage_dir=str(tmp_path))
    assert fresh.get_profile('e1')['slots']['talkativeness']['status'] == STATUS_FILLED


def test_observe_never_marks_observable_as_askable(svc):
    """观察类字段没有 asked 状态（设计文档 §5.6）。"""
    _feed(svc, 20, text='嗯')
    assert svc.get_profile('e1')['slots']['talkativeness']['ask_count'] == 0
