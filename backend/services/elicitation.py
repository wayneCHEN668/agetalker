"""采集规划器：这一轮该不该采集、采哪个字段。

纯函数——不调 LLM、不碰 IO。这让设计文档 §4.2 的两套门槛可以被穷举测试：
本设计里最容易出错的逻辑，恰好是最容易测的。

两种采集，两套门槛（设计文档 §4.2）
------------------------------------
顺水推舟（低门槛）：老人自己提到了线索，AI 顺着多问一句。它**不改变话题**，
只是深入老人自己已经打开的话头。所以允许在敏感类别下进行——老人说"最近腰疼
得睡不着"，这既是抑郁的躯体化信号，也是身体状况线索，顺着关心一句完全恰当。
唯一硬禁止是危机。

主动起话头（高门槛）：为了填某个空字段而开新话题。必须全部条件满足，因为
在敏感叙事中开新话题就是打断。

采集不抢 strategy_id 的决策权（设计文档 §4.4）：策略仍然决定这一轮 AI 要做
什么，采集只是在 prompt 里追加一句"顺带关心一下 X"。
"""

from typing import NamedTuple

from config import ELICIT_COOLDOWN_TURNS, ELICIT_MAX_PER_SESSION
from services.profile_schema import askable_by_priority, is_askable
from services.profile_service import STATUS_STALE, needs_attention

MODE_NONE       = 'none'
MODE_FOLLOW_UP  = 'follow_up'
MODE_OPEN_TOPIC = 'open_topic'

# 允许主动起话头的类别。敏感类别一律不行——开新话题就是打断。
_SAFE_CATEGORIES = ('neutral', 'positive')


class ElicitPlan(NamedTuple):
    mode: str
    slot: str
    is_stale: bool


_NO_PLAN = ElicitPlan(MODE_NONE, '', False)


def _is_stale(profile: dict, slot_name: str) -> bool:
    slot = profile.get('slots', {}).get(slot_name)
    return bool(slot) and slot['status'] == STATUS_STALE


def plan_elicitation(
    profile: dict,
    *,
    slot_hint: str,
    category: str,
    phase: str,
    crisis: bool,
    crisis_vigilant: bool,
    restrain_questions: bool,
    turns_since_last_elicit: int,
    elicited_this_session: int,
    address_asked_this_session: bool,
) -> ElicitPlan:
    """决定这一轮的采集动作。

    Args:
        profile: ProfileService.get_profile() 的返回值
        slot_hint: 路由模型报的线索字段名（可能为空或非法）
        category: 路由判定的心理类别
        phase: 会话阶段 opening / deepening / closing
        crisis: 这一轮是否命中危机
        crisis_vigilant: 是否处于危机警戒期
        restrain_questions: 现有问句节流器的判断（必须复用，不能另起一套）
        turns_since_last_elicit: 距上次主动采集过了几轮
        elicited_this_session: 本次会话已经主动起了几个话头（不含 address）
        address_asked_this_session: 本次会话是否已经问过称呼
    """
    # ── 危机：两种采集都硬禁止 ──
    if crisis or crisis_vigilant:
        return _NO_PLAN

    # ── 顺水推舟：门槛最低，优先于开新话题（更不打扰）──
    # 这一轮给了线索，就只看这条线索能不能顺下去：能就顺水推舟；不能
    # （字段非法/不可问，或已经 filled/declined）就这一轮什么都不采，
    # 不能倒回去找别的字段主动开话头——那是另一件事，不能拿线索当由头
    # 顺手做了（设计文档 §4.1：宁可不采）。只有压根没给线索（空字符串）
    # 才继续往下走主动起话头的安全窗口判断。
    if slot_hint:
        if is_askable(slot_hint) and needs_attention(profile, slot_hint):
            return ElicitPlan(MODE_FOLLOW_UP, slot_hint, _is_stale(profile, slot_hint))
        return _NO_PLAN

    # ── 安全窗口：以下所有"主动起话头"都要过这一关 ──
    # address 破的是优先级和时机的例（不等线索、不等冷却、不占名额），
    # 不是安全窗口的例（设计文档 §3.5）。
    in_safe_window = (
        category in _SAFE_CATEGORIES
        and phase != 'closing'
        and not restrain_questions
    )
    if not in_safe_window:
        return _NO_PLAN

    # ── 称呼：唯一一个应该直接问的字段，不等线索也不等冷却 ──
    if not address_asked_this_session and needs_attention(profile, 'address'):
        return ElicitPlan(MODE_OPEN_TOPIC, 'address', _is_stale(profile, 'address'))

    # ── 普通主动起话头：还要过冷却和会话名额 ──
    if turns_since_last_elicit < ELICIT_COOLDOWN_TURNS:
        return _NO_PLAN
    if elicited_this_session >= ELICIT_MAX_PER_SESSION:
        return _NO_PLAN

    for name in askable_by_priority():
        if name == 'address':
            continue                     # 上面已经单独处理过
        if needs_attention(profile, name):
            return ElicitPlan(MODE_OPEN_TOPIC, name, _is_stale(profile, name))

    return _NO_PLAN
