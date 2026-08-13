"""slot 状态机。这是整套画像机制里最容易出错、也最容易测的部分。"""
from datetime import datetime, timedelta, timezone

import pytest

from services.profile_service import (
    STATUS_UNKNOWN, STATUS_ASKED, STATUS_FILLED, STATUS_DECLINED, STATUS_STALE,
    empty_profile, mark_asked, mark_filled, mark_declined,
    refresh_stale, needs_attention,
)

BJ = timezone(timedelta(hours=8))


def _p():
    return empty_profile('elder_test')


def test_empty_profile_has_every_slot_unknown():
    p = _p()
    assert p['elder_id'] == 'elder_test'
    assert p['slots']['address']['status'] == STATUS_UNKNOWN
    assert p['slots']['address']['ask_count'] == 0
    assert p['slots']['hometown']['value'] == ''


def test_unknown_to_asked_to_filled():
    p = _p()
    mark_asked(p, 'hometown')
    assert p['slots']['hometown']['status'] == STATUS_ASKED
    assert p['slots']['hometown']['ask_count'] == 1
    assert p['slots']['hometown']['last_asked']

    mark_filled(p, 'hometown', '河北保定', evidence='我老家保定的')
    s = p['slots']['hometown']
    assert s['status'] == STATUS_FILLED
    assert s['value'] == '河北保定'
    assert s['source'] == 'conversation'
    assert s['evidence'] == '我老家保定的'
    assert s['last_filled']


def test_second_ask_without_answer_becomes_declined():
    """设计文档 §5.4：沉默即拒绝。

    这是整套机制里最重要的一条硬闸。老人两次都岔开话题，那就是不想说，
    不管他有没有明说出口。
    """
    p = _p()
    mark_asked(p, 'occupation')
    assert p['slots']['occupation']['status'] == STATUS_ASKED
    mark_asked(p, 'occupation')
    assert p['slots']['occupation']['status'] == STATUS_DECLINED
    assert not needs_attention(p, 'occupation')


def test_declined_slot_is_never_asked_again():
    p = _p()
    mark_declined(p, 'sleep')
    before = p['slots']['sleep']['ask_count']
    mark_asked(p, 'sleep')
    assert p['slots']['sleep']['status'] == STATUS_DECLINED
    assert p['slots']['sleep']['ask_count'] == before, 'declined 之后连计数都不该再动'


def test_declined_blocks_asking_but_not_recording():
    """declined 只挡「问」，不挡「记」。

    老人当初两次没答，后来自己主动说了——当然要记。反过来会导致他明明说了、
    AI 却装作不知道，比重复问更伤人。
    """
    p = _p()
    mark_asked(p, 'hobbies_current')
    mark_asked(p, 'hobbies_current')
    assert p['slots']['hobbies_current']['status'] == STATUS_DECLINED

    mark_filled(p, 'hobbies_current', '下象棋')
    assert p['slots']['hobbies_current']['status'] == STATUS_FILLED
    assert p['slots']['hobbies_current']['value'] == '下象棋'


def test_filled_then_asked_again_stays_filled():
    p = _p()
    mark_filled(p, 'hometown', '保定')
    mark_asked(p, 'hometown')
    assert p['slots']['hometown']['status'] == STATUS_FILLED


def test_halflife_turns_filled_into_stale():
    p = _p()
    long_ago = datetime.now(BJ) - timedelta(days=200)
    mark_filled(p, 'hobbies_current', '下象棋', now=long_ago)   # 半衰期 180 天
    changed = refresh_stale(p)
    assert 'hobbies_current' in changed
    assert p['slots']['hobbies_current']['status'] == STATUS_STALE
    assert p['slots']['hobbies_current']['value'] == '下象棋', 'stale 只改状态，不丢值'
    assert needs_attention(p, 'hobbies_current'), 'stale 要能被重新确认'


def test_fresh_filled_does_not_go_stale():
    p = _p()
    mark_filled(p, 'hobbies_current', '下象棋',
                now=datetime.now(BJ) - timedelta(days=10))
    assert refresh_stale(p) == []
    assert p['slots']['hobbies_current']['status'] == STATUS_FILLED


def test_never_expiring_slot_never_goes_stale():
    """设计文档 §3.6：家乡、职业、以前的爱好永不过期。"""
    p = _p()
    ancient = datetime.now(BJ) - timedelta(days=3650)
    for name in ('hometown', 'occupation', 'hobbies_past', 'address', 'birth_year'):
        mark_filled(p, name, 'x', now=ancient)
    assert refresh_stale(p) == []


def test_refresh_stale_ignores_unfilled():
    p = _p()
    mark_asked(p, 'sleep')
    assert refresh_stale(p) == []


def test_needs_attention_matrix():
    p = _p()
    assert needs_attention(p, 'sleep'), 'unknown 需要采'
    mark_asked(p, 'sleep')
    assert needs_attention(p, 'sleep'), 'asked 但没填上，还能再问一次'
    mark_filled(p, 'sleep', '睡得浅')
    assert not needs_attention(p, 'sleep'), 'filled 且没过期，不用再问'


def test_invalid_slot_name_is_ignored_not_raised():
    """采集是增强能力，非法字段名不能把对话搞崩（设计文档 §9）。"""
    p = _p()
    mark_asked(p, 'favorite_color')
    mark_filled(p, 'favorite_color', 'x')
    mark_declined(p, 'favorite_color')
    assert 'favorite_color' not in p['slots']
    assert not needs_attention(p, 'favorite_color')
