"""采集规划器：两套门槛的穷举测试。

顺水推舟（低门槛）：老人自己提到了线索，AI 顺着多问一句。不改变话题，
所以**允许在敏感类别下进行**，唯一硬禁止是危机。

主动起话头（高门槛）：为了填空字段而开新话题，必须全部条件满足。
"""
import pytest

from services.elicitation import (
    MODE_NONE, MODE_FOLLOW_UP, MODE_OPEN_TOPIC, plan_elicitation,
)
from services.profile_service import (
    empty_profile, mark_filled, mark_asked, refresh_stale, STATUS_STALE,
)
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))


def _plan(profile=None, **kw):
    """默认给一组"安全窗口全部满足"的参数，测试只覆盖它关心的那一项。"""
    base = dict(
        slot_hint='',
        category='neutral',
        phase='deepening',
        crisis=False,
        crisis_vigilant=False,
        restrain_questions=False,
        turns_since_last_elicit=99,
        elicited_this_session=0,
        address_asked_this_session=True,   # 默认已问过，避免每个用例都被 address 抢走
    )
    base.update(kw)
    return plan_elicitation(profile if profile is not None else empty_profile('e'), **base)


# ─── 顺水推舟 ────────────────────────────────────────────────────────────────

def test_follow_up_when_hint_present():
    p = _plan(slot_hint='sleep')
    assert p.mode == MODE_FOLLOW_UP
    assert p.slot == 'sleep'


def test_follow_up_allowed_in_sensitive_category():
    """老人说"最近腰疼得睡不着"——既是抑郁躯体化信号，也是身体状况线索。
    顺着关心一句完全恰当（设计文档 §4.2）。"""
    for cat in ('depression', 'anxiety', 'anger', 'loneliness', 'grief'):
        p = _plan(slot_hint='chronic_conditions', category=cat)
        assert p.mode == MODE_FOLLOW_UP, cat


def test_follow_up_allowed_while_restraining_questions():
    """顺水推舟不是新增提问，是顺着已开的话头关心一句。"""
    p = _plan(slot_hint='sleep', restrain_questions=True)
    assert p.mode == MODE_FOLLOW_UP


def test_follow_up_blocked_by_crisis():
    assert _plan(slot_hint='sleep', crisis=True).mode == MODE_NONE
    assert _plan(slot_hint='sleep', crisis_vigilant=True).mode == MODE_NONE


def test_invalid_hint_is_ignored():
    """设计文档 §4.1：slot_hint 非法时一律当空，宁可不采。"""
    assert _plan(slot_hint='favorite_color').mode == MODE_NONE
    assert _plan(slot_hint='talkativeness').mode == MODE_NONE, '观察类字段永远不问'
    assert _plan(slot_hint='location').mode == MODE_NONE, '外部录入字段不问'


def test_follow_up_skipped_when_slot_already_fresh():
    prof = empty_profile('e')
    mark_filled(prof, 'sleep', '睡得浅')
    assert _plan(prof, slot_hint='sleep').mode == MODE_NONE


def test_follow_up_on_stale_slot_is_a_confirmation():
    prof = empty_profile('e')
    mark_filled(prof, 'hobbies_current', '下象棋',
                now=datetime.now(BJ) - timedelta(days=200))
    refresh_stale(prof)
    p = _plan(prof, slot_hint='hobbies_current')
    assert p.mode == MODE_FOLLOW_UP
    assert p.is_stale is True


def test_follow_up_skipped_when_declined():
    prof = empty_profile('e')
    mark_asked(prof, 'sleep')
    mark_asked(prof, 'sleep')       # --> declined
    assert _plan(prof, slot_hint='sleep').mode == MODE_NONE


# ─── 主动起话头：安全窗口逐条拦截 ────────────────────────────────────────────

def test_open_topic_in_safe_window():
    p = _plan()
    assert p.mode == MODE_OPEN_TOPIC
    assert p.slot == 'sensory_hearing', 'address 已问过时，下一个是听力'


@pytest.mark.parametrize('cat', ['depression', 'anxiety', 'anger', 'loneliness', 'grief'])
def test_open_topic_blocked_in_sensitive_category(cat):
    assert _plan(category=cat).mode == MODE_NONE


def test_open_topic_allowed_in_positive():
    assert _plan(category='positive').mode == MODE_OPEN_TOPIC


def test_open_topic_blocked_in_closing_phase():
    assert _plan(phase='closing').mode == MODE_NONE


def test_open_topic_blocked_when_restraining_questions():
    """必须复用现有问句节流器：否则策略问一句、采集问一句，老人体验到连环追问。"""
    assert _plan(restrain_questions=True).mode == MODE_NONE


def test_open_topic_blocked_by_crisis_vigilance():
    assert _plan(crisis_vigilant=True).mode == MODE_NONE


def test_open_topic_blocked_by_cooldown():
    assert _plan(turns_since_last_elicit=1).mode == MODE_NONE
    assert _plan(turns_since_last_elicit=5).mode == MODE_OPEN_TOPIC


def test_open_topic_blocked_by_session_quota():
    assert _plan(elicited_this_session=2).mode == MODE_NONE
    assert _plan(elicited_this_session=1).mode == MODE_OPEN_TOPIC


def test_open_topic_picks_highest_priority_unfilled():
    prof = empty_profile('e')
    mark_filled(prof, 'sensory_hearing', '有点背')
    mark_filled(prof, 'sensory_vision', '还行')
    p = _plan(prof)
    assert p.slot == 'daily_routine'


def test_open_topic_none_when_everything_settled():
    prof = empty_profile('e')
    for name in list(prof['slots']):
        mark_filled(prof, name, 'x')
    assert _plan(prof).mode == MODE_NONE


# ─── address 的特殊路径 ──────────────────────────────────────────────────────

def test_address_asked_first_and_exempt_from_cooldown_and_quota():
    """设计文档 §3.5/§4.3：不等冷却、不等线索、不占会话名额。"""
    p = _plan(address_asked_this_session=False,
              turns_since_last_elicit=0,
              elicited_this_session=99)
    assert p.mode == MODE_OPEN_TOPIC
    assert p.slot == 'address'


def test_address_still_respects_safe_window():
    """它破的是优先级和时机的例，不是安全窗口的例。"""
    for kw in ({'category': 'grief'}, {'phase': 'closing'},
               {'crisis_vigilant': True}, {'restrain_questions': True}):
        p = _plan(address_asked_this_session=False, **kw)
        assert p.mode == MODE_NONE, kw


def test_address_not_reasked_within_same_session():
    p = _plan(address_asked_this_session=True)
    assert p.slot != 'address'


def test_follow_up_wins_over_address():
    """顺水推舟比开新话题更不打扰，让它先走。"""
    p = _plan(slot_hint='sleep', address_asked_this_session=False)
    assert p.mode == MODE_FOLLOW_UP
    assert p.slot == 'sleep'


def test_declined_address_never_asked_again():
    prof = empty_profile('e')
    mark_asked(prof, 'address')
    mark_asked(prof, 'address')      # --> declined
    p = _plan(prof, address_asked_this_session=False)
    assert p.slot != 'address'
