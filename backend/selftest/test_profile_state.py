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


# ─── address / birth_year 特殊路径 ───────────────────────────────────────────

from datetime import date

from services.profile_service import (
    DEFAULT_ADDRESS, render_address, set_birth_year, compute_age, render_profile,
)


def test_address_falls_back_to_nin_when_unknown():
    """设计文档 §3.5：绝不留空、绝不自己编一个称呼。

    这条要单独测，因为它的失败形式是"生成一句带空洞的话"（「，上午好啊」），
    容易在集成层被忽略。
    """
    p = _p()
    assert render_address(p) == DEFAULT_ADDRESS == '您'


def test_address_falls_back_when_declined():
    p = _p()
    mark_asked(p, 'address')
    mark_asked(p, 'address')
    assert p['slots']['address']['status'] == STATUS_DECLINED
    assert render_address(p) == '您'


def test_address_uses_elders_own_words_verbatim():
    """称呼反映身份认同，不规范化、不自作主张加后缀。"""
    p = _p()
    mark_filled(p, 'address', '王老师')
    assert render_address(p) == '王老师'


def test_address_blank_value_still_falls_back():
    p = _p()
    p['slots']['address']['status'] = STATUS_FILLED
    p['slots']['address']['value'] = '   '
    assert render_address(p) == '您'


def test_birth_year_rejects_an_age_number():
    """设计文档 §3.6：存 age: 83 一年后就是错的，且没有机制会发现。"""
    p = _p()
    assert set_birth_year(p, 83) is False
    assert p['slots']['birth_year']['status'] == STATUS_UNKNOWN
    assert compute_age(p) is None


def test_birth_year_accepts_four_digit_year():
    p = _p()
    assert set_birth_year(p, 1943, evidence='我 43 年生的') is True
    assert p['slots']['birth_year']['value'] == '1943'
    assert p['slots']['birth_year']['status'] == STATUS_FILLED


def test_birth_year_accepts_string_and_rejects_garbage():
    p = _p()
    assert set_birth_year(p, ' 1938 ') is True
    assert set_birth_year(p, '属马') is False
    assert set_birth_year(p, '') is False
    assert set_birth_year(p, 2999) is False


def test_age_is_computed_not_stored_and_rolls_over():
    """同一份数据，跨年之后算出来的年龄要 +1。"""
    p = _p()
    set_birth_year(p, 1943)
    assert compute_age(p, today=date(2026, 8, 13)) == 83
    assert compute_age(p, today=date(2027, 1, 1)) == 84
    assert 'age' not in p['slots']['birth_year']


def test_render_profile_empty_returns_empty_string():
    assert render_profile(_p()) == ''


def test_render_profile_only_shows_known_values():
    p = _p()
    mark_filled(p, 'hometown', '河北保定')
    mark_asked(p, 'sleep')            # 问过但没答上，不该出现在渲染里
    text = render_profile(p)
    assert '河北保定' in text
    assert '睡' not in text


def test_render_profile_marks_stale_values():
    """stale 要在 prompt 里标出来，生成侧才知道该用「确认」而不是「陈述」。"""
    p = _p()
    mark_filled(p, 'hobbies_current', '下象棋',
                now=datetime.now(BJ) - timedelta(days=200))
    refresh_stale(p)
    text = render_profile(p)
    assert '下象棋' in text
    assert '可能过时' in text


def test_render_profile_includes_age_not_birth_year():
    p = _p()
    set_birth_year(p, 1943)
    text = render_profile(p)
    assert '1943' not in text, '给模型看年龄，不是出生年份'
    assert '岁' in text
