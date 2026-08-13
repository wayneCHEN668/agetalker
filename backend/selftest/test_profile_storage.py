"""画像持久化。存储失败绝不能影响对话（设计文档 §9）。"""
import json
from pathlib import Path

import pytest

from services.profile_service import (
    ProfileService, STATUS_FILLED, mark_filled,
)


@pytest.fixture
def svc(tmp_path):
    return ProfileService(storage_dir=str(tmp_path))


def test_first_access_returns_empty_profile(svc):
    p = svc.get_profile('elder_a')
    assert p['elder_id'] == 'elder_a'
    assert p['slots']['hometown']['status'] == 'unknown'


def test_save_and_reload(svc, tmp_path):
    p = svc.get_profile('elder_a')
    mark_filled(p, 'hometown', '河北保定')
    svc.save('elder_a')

    assert (tmp_path / 'elder_a.json').exists()
    fresh = ProfileService(storage_dir=str(tmp_path))
    assert fresh.get_profile('elder_a')['slots']['hometown']['value'] == '河北保定'


def test_no_temp_file_left_behind(svc, tmp_path):
    p = svc.get_profile('elder_a')
    mark_filled(p, 'hometown', '保定')
    svc.save('elder_a')
    assert list(tmp_path.glob('*.tmp')) == []


def test_corrupted_file_falls_back_to_empty(tmp_path):
    """台账已有此模式：文件坏了按空处理，不能让对话起不来。"""
    (tmp_path / 'elder_b.json').write_text('{ this is not json', encoding='utf-8')
    svc = ProfileService(storage_dir=str(tmp_path))
    p = svc.get_profile('elder_b')
    assert p['slots']['hometown']['status'] == 'unknown'


def test_non_dict_json_falls_back_to_empty(tmp_path):
    """合法 JSON 但顶层不是对象（比如 null）：按空画像处理，不能抛异常。"""
    (tmp_path / 'elder_x.json').write_text('null', encoding='utf-8')
    svc = ProfileService(storage_dir=str(tmp_path))
    p = svc.get_profile('elder_x')
    assert p['slots']['hometown']['status'] == 'unknown'


def test_missing_fields_are_backfilled(tmp_path):
    """早期文件缺字段时补齐，不能 KeyError。"""
    (tmp_path / 'elder_c.json').write_text(
        json.dumps({'elder_id': 'elder_c', 'slots': {
            'hometown': {'value': '保定', 'status': 'filled'}
        }}, ensure_ascii=False),
        encoding='utf-8',
    )
    svc = ProfileService(storage_dir=str(tmp_path))
    p = svc.get_profile('elder_c')
    assert p['slots']['hometown']['value'] == '保定'
    assert p['slots']['hometown']['ask_count'] == 0, '缺的字段要补默认值'
    assert p['slots']['sleep']['status'] == 'unknown', '整个缺的 slot 要补出来'


def test_elder_id_path_traversal_is_sanitized(svc, tmp_path):
    svc.get_profile('../../etc/passwd')
    svc.save('../../etc/passwd')
    written = list(tmp_path.glob('*.json'))
    assert len(written) == 1
    assert '..' not in written[0].name


def test_get_context_and_address(svc):
    p = svc.get_profile('elder_a')
    mark_filled(p, 'address', '王老师')
    mark_filled(p, 'hometown', '保定')
    assert svc.get_address('elder_a') == '王老师'
    assert '保定' in svc.get_context('elder_a')
    assert svc.get_address('elder_unknown') == '您'


def test_note_asked_persists(svc, tmp_path):
    svc.note_asked('elder_a', 'sleep')
    fresh = ProfileService(storage_dir=str(tmp_path))
    assert fresh.get_profile('elder_a')['slots']['sleep']['ask_count'] == 1


def test_save_failure_does_not_raise(svc, monkeypatch):
    """存储失败只记 error，不能把这一轮对话搞崩。"""
    def boom(*a, **k):
        raise OSError('disk full')
    monkeypatch.setattr(Path, 'write_text', boom)
    svc.get_profile('elder_a')
    svc.save('elder_a')          # 不应抛异常
