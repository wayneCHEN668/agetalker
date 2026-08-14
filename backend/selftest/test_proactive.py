"""主动开口护栏。这些不是功能需求，是"别让这东西变成扰民设备"。"""
from datetime import datetime, timedelta, timezone

import pytest

from services.proactive import ProactiveGuard, in_quiet_hours

BJ = timezone(timedelta(hours=8))


def _t(h, m=0, day=13):
    return datetime(2026, 8, day, h, m, tzinfo=BJ)


@pytest.mark.parametrize('hour,quiet', [
    (20, False), (21, True), (23, True), (0, True),
    (6, True), (7, False), (10, False),
])
def test_quiet_hours_boundaries(hour, quiet):
    """21:00 起静默，07:00 解除。含起点不含终点。"""
    assert in_quiet_hours(_t(hour)) is quiet


def test_quiet_minute_boundaries():
    assert in_quiet_hours(_t(20, 59)) is False
    assert in_quiet_hours(_t(21, 0)) is True
    assert in_quiet_hours(_t(6, 59)) is True
    assert in_quiet_hours(_t(7, 0)) is False


def test_can_speak_in_daytime():
    g = ProactiveGuard()
    ok, why = g.can_speak('e1', crisis_vigilant=False, now=_t(10))
    assert ok, why


def test_blocked_in_quiet_hours():
    """作息字段抽错一个数字就可能变成半夜三点自己说话——这是硬边界。"""
    g = ProactiveGuard()
    ok, why = g.can_speak('e1', crisis_vigilant=False, now=_t(3))
    assert not ok
    assert 'quiet' in why


def test_blocked_during_crisis_vigilance():
    """刚经历过危机对话，设备过一会儿自己出声是惊吓，不是陪伴。"""
    g = ProactiveGuard()
    ok, why = g.can_speak('e1', crisis_vigilant=True, now=_t(10))
    assert not ok
    assert 'crisis' in why


def test_daily_quota():
    g = ProactiveGuard()
    for _ in range(3):
        assert g.can_speak('e1', crisis_vigilant=False, now=_t(10))[0]
        g.note_spoke('e1', now=_t(10))
        g.note_answered('e1')
    ok, why = g.can_speak('e1', crisis_vigilant=False, now=_t(10))
    assert not ok
    assert 'daily' in why


def test_quota_resets_next_day():
    g = ProactiveGuard()
    for _ in range(3):
        g.note_spoke('e1', now=_t(10, day=13))
        g.note_answered('e1')
    assert not g.can_speak('e1', crisis_vigilant=False, now=_t(10, day=13))[0]
    assert g.can_speak('e1', crisis_vigilant=False, now=_t(10, day=14))[0]


def test_gives_up_after_consecutive_no_answers():
    """连吃两次闭门羹就停手；否则设备变成定时扰民的喇叭，扰的是隔壁床的人。"""
    g = ProactiveGuard()
    g.note_spoke('e1', now=_t(9)); g.note_no_answer('e1')
    assert g.can_speak('e1', crisis_vigilant=False, now=_t(10))[0]
    g.note_spoke('e1', now=_t(10)); g.note_no_answer('e1')
    ok, why = g.can_speak('e1', crisis_vigilant=False, now=_t(11))
    assert not ok
    assert 'no_answer' in why


def test_answer_resets_no_answer_streak():
    g = ProactiveGuard()
    g.note_spoke('e1', now=_t(9)); g.note_no_answer('e1')
    g.note_spoke('e1', now=_t(10)); g.note_answered('e1')
    assert g.can_speak('e1', crisis_vigilant=False, now=_t(11))[0]


def test_elders_are_isolated():
    g = ProactiveGuard()
    for _ in range(3):
        g.note_spoke('e1', now=_t(10)); g.note_answered('e1')
    assert not g.can_speak('e1', crisis_vigilant=False, now=_t(10))[0]
    assert g.can_speak('e2', crisis_vigilant=False, now=_t(10))[0]
