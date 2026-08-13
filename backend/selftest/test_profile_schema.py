"""画像字段定义的静态约束。

这些断言看着琐碎，但它们保护的是两条真实的失败路径：
1. 优先级重复 --> askable_by_priority() 的顺序变成不确定的，"该问哪个"就成了随机
2. 缺 zh --> 注入 prompt 时出现字段英文名，老人会听到"请问您的 sensory_hearing"
"""
import pytest

from services.profile_schema import (
    ASKABLE, OBSERVABLE, EXTERNAL, NEVER, SLOTS,
    ASKABLE_SLOTS, OBSERVABLE_SLOTS,
    is_valid_slot, is_askable, askable_by_priority, slot_zh,
)


def test_every_slot_has_required_keys():
    for name, cfg in SLOTS.items():
        assert cfg['kind'] in (ASKABLE, OBSERVABLE, EXTERNAL), name
        assert 'halflife_days' in cfg, name
        assert cfg['zh'], f'{name} 缺中文名，会把英文字段名念给老人听'


def test_askable_priorities_are_unique_and_positive():
    prios = [SLOTS[n]['priority'] for n in ASKABLE_SLOTS]
    assert len(prios) == len(set(prios)), '优先级重复会让"该问哪个"变成随机'
    assert all(p > 0 for p in prios)


def test_address_is_top_priority():
    # 设计文档 §3.4：称呼每句话都用得上，且是定时招呼的前置
    assert askable_by_priority()[0] == 'address'


def test_never_expiring_slots():
    # 设计文档 §3.6：只有出生年份是真的永不过期
    for name in ('address', 'birth_year', 'hobbies_past', 'occupation', 'hometown'):
        assert SLOTS[name]['halflife_days'] is NEVER, name


def test_observable_slots_are_not_askable():
    # 设计文档 §3.2：性格只能观察，问"您性格怎么样"是荒谬的
    for name in OBSERVABLE_SLOTS:
        assert not is_askable(name), name
    assert 'talkativeness' in OBSERVABLE_SLOTS
    assert 'emotional_baseline' in OBSERVABLE_SLOTS


def test_external_slots_exist_but_are_not_askable():
    # 设计文档 §3.2：本期只占位，由后续立项的家属端填入
    for name in ('location', 'medication_names', 'emergency_contact', 'room_number'):
        assert is_valid_slot(name)
        assert not is_askable(name)


def test_unknown_slot_rejected():
    # 设计文档 §4.1：slot_hint 非法时一律当空，宁可不采
    assert not is_valid_slot('')
    assert not is_valid_slot('favorite_color')
    assert not is_askable('favorite_color')


def test_slot_zh_falls_back_to_name():
    assert slot_zh('address') == '称呼'
    assert slot_zh('favorite_color') == 'favorite_color'
