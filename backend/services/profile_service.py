"""画像服务：结构化 slot 的状态机 + 持久化 + 后台抽取。

和 memory_service 的分工（设计文档 §3.1）
------------------------------------------
台账（memory_service）是**叙事记忆**：自由文本、无限增长、为了"AI 记得你说过
什么"。画像是**结构化档案**：有限字段、可枚举、为了"AI 知道你是谁"，并且能
回答"这个字段填了没有"——而它正是"不重复询问"的前提。

两者不合并：合并之后就没法判断字段填没填。存储也分开（独立文件、独立锁），
否则 memory_service 会变成一个什么都干的模块。

为什么状态不能是布尔值（设计文档 §5.1）
---------------------------------------
"字段有值 = 问过了"会在一个地方致命地失效：问了但老人岔开话题没答，字段仍是
空的，规划器下次又问、再下次又问。老人体验到的是被逼问，系统却自认为"还没
采到，该问"。所以 asked 必须是独立于 filled 的状态。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import ELICIT_MAX_ASK_COUNT
from services.profile_schema import SLOTS, is_valid_slot

logger = logging.getLogger(__name__)

_BEIJING = timezone(timedelta(hours=8))

# slot 状态（设计文档 §5.2）
STATUS_UNKNOWN  = 'unknown'
STATUS_ASKED    = 'asked'
STATUS_FILLED   = 'filled'
STATUS_DECLINED = 'declined'
STATUS_STALE    = 'stale'


def _now() -> datetime:
    return datetime.now(_BEIJING)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _parse(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# ─── 纯函数（不依赖 LLM / IO，可独立测试）─────────────────────────────────────


def empty_slot() -> dict:
    return {
        'value':       '',
        'status':      STATUS_UNKNOWN,
        'ask_count':   0,
        'last_asked':  '',
        'last_filled': '',
        # source / confidence / evidence 本期不做界面，但字段先带上：
        # 补字段比补数据便宜，将来要开护理员视图时不用回头重洗数据。
        'source':      '',
        'confidence':  '',
        'evidence':    '',
    }


def empty_profile(elder_id: str) -> dict:
    return {
        'elder_id': elder_id,
        'slots': {name: empty_slot() for name in SLOTS},
        # 观察类字段的原始计数器，见 Task 9
        'observations': {},
    }


def mark_asked(profile: dict, slot_name: str, now: Optional[datetime] = None) -> None:
    """记录"这一轮问了这个字段"。

    沉默即拒绝（设计文档 §5.4）：问到 ELICIT_MAX_ASK_COUNT 次仍未填上，自动降为
    declined，永不再问。没有这条硬闸，前面所有的"安全窗口""节流"都只是降低
    频率——一个永远填不上的字段最终一定会被问到第五次、第十次。
    """
    slot = profile.get('slots', {}).get(slot_name)
    if slot is None:
        return
    if slot['status'] == STATUS_DECLINED:
        return                      # 终态，连计数都不再动

    slot['ask_count'] += 1
    slot['last_asked'] = _iso(now)

    if slot['status'] == STATUS_FILLED:
        return                      # 已经有值了，问一句只是确认，不改状态

    slot['status'] = STATUS_ASKED
    if slot['ask_count'] >= ELICIT_MAX_ASK_COUNT:
        slot['status'] = STATUS_DECLINED
        logger.info(f"画像字段 {slot_name} 连问 {slot['ask_count']} 次未果，不再问")


def mark_filled(
    profile: dict,
    slot_name: str,
    value: str,
    source: str = 'conversation',
    confidence: str = 'high',
    evidence: str = '',
    now: Optional[datetime] = None,
) -> None:
    """记下一个字段的值。

    **从任何状态都能填，包括 declined。** declined 只挡「问」，不挡「记」：
    老人当初两次没答，后来自己主动说了——当然要记。反过来会导致他明明说了、
    AI 却装作不知道，比重复问更伤人。
    """
    slot = profile.get('slots', {}).get(slot_name)
    if slot is None or not str(value).strip():
        return
    slot['value']       = str(value).strip()
    slot['status']      = STATUS_FILLED
    slot['last_filled'] = _iso(now)
    slot['source']      = source
    slot['confidence']  = confidence
    if evidence:
        slot['evidence'] = evidence[:100]


def mark_declined(profile: dict, slot_name: str) -> None:
    """老人明确拒绝。终态。"""
    slot = profile.get('slots', {}).get(slot_name)
    if slot is None:
        return
    slot['status'] = STATUS_DECLINED


def refresh_stale(profile: dict, now: Optional[datetime] = None) -> list[str]:
    """把过了半衰期的 filled 字段转成 stale，返回被转的字段名。

    stale 不丢值——它走的是"确认"话术（「您那个腰，这阵子还疼不」），不是
    重新提问（「您平时有啥爱好」）。确认已知信息是亲近的表现，重新提问是
    疏远的表现（设计文档 §5.5）。
    """
    now = now or _now()
    changed: list[str] = []
    for name, slot in profile.get('slots', {}).items():
        if slot['status'] != STATUS_FILLED:
            continue
        halflife = SLOTS[name]['halflife_days']
        if halflife is None:
            continue                                # 永不过期
        filled_at = _parse(slot['last_filled'])
        if filled_at is None:
            continue
        if (now - filled_at).days >= halflife:
            slot['status'] = STATUS_STALE
            changed.append(name)
    return changed


def needs_attention(profile: dict, slot_name: str) -> bool:
    """这个字段现在还值不值得问/确认。"""
    if not is_valid_slot(slot_name):
        return False
    slot = profile.get('slots', {}).get(slot_name)
    if slot is None:
        return False
    return slot['status'] in (STATUS_UNKNOWN, STATUS_ASKED, STATUS_STALE)
