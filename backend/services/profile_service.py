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
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import ELICIT_MAX_ASK_COUNT
from services.profile_schema import (
    SLOTS, OBSERVABLE_SLOTS, askable_by_priority, is_valid_slot, slot_zh,
)

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


# ─── address / birth_year 特殊路径 ───────────────────────────────────────────

# 称呼未知或被拒绝时的兜底。绝不留空、绝不自己编一个称呼——
# 编错称呼比不叫名字伤人得多（设计文档 §3.5）。
DEFAULT_ADDRESS = '您'


def render_address(profile: dict) -> str:
    """该怎么称呼他。任何拿不准的情况一律返回「您」。"""
    slot = profile.get('slots', {}).get('address')
    if slot and slot['status'] == STATUS_FILLED and slot['value'].strip():
        return slot['value'].strip()
    return DEFAULT_ADDRESS


def set_birth_year(
    profile: dict,
    raw_value,
    source: str = 'conversation',
    evidence: str = '',
    now: Optional[datetime] = None,
) -> bool:
    """写入出生年份。只接受四位年份，成功返回 True。

    传进来一个年龄数字（比如 83）会被拒绝：存年龄一年后就是错的，而且没有
    任何机制会发现它错了。年龄由 compute_age() 每次读时算（设计文档 §3.6）。
    """
    try:
        year = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return False
    this_year = (now or _now()).year
    if not (1900 <= year <= this_year):
        return False
    mark_filled(profile, 'birth_year', str(year), source=source,
                evidence=evidence, now=now)
    return True


def compute_age(profile: dict, today: Optional[date] = None) -> Optional[int]:
    """按当前日期算年龄。拿不准时返回 None——猜错会让 AI 聊一个他没经历过的年代。"""
    slot = profile.get('slots', {}).get('birth_year')
    if not slot or not slot['value']:
        return None
    try:
        year = int(slot['value'])
    except ValueError:
        return None
    today = today or _now().date()
    if not (1900 <= year <= today.year):
        return None
    return today.year - year


def render_profile(profile: dict) -> str:
    """渲染成注入 system prompt 的文本。没有任何已知内容时返回空串。

    只渲染真正有值的字段（filled / stale）。asked-but-unanswered 绝不出现——
    那会让模型以为自己知道点什么，然后编。
    """
    if not profile:
        return ''

    lines: list[str] = []
    slots = profile.get('slots', {})

    age = compute_age(profile)
    if age is not None:
        lines.append(f'- 岁数：{age} 岁')

    for name in askable_by_priority():
        if name == 'birth_year':
            continue                       # 上面已经按年龄渲染过了
        slot = slots.get(name)
        if not slot or slot['status'] not in (STATUS_FILLED, STATUS_STALE):
            continue
        if not slot['value'].strip():
            continue
        suffix = '（以前记的，可能过时了，可以顺口确认一下）' \
            if slot['status'] == STATUS_STALE else ''
        lines.append(f'- {slot_zh(name)}：{slot["value"]}{suffix}')

    observed = _render_observations(slots)
    if observed:
        lines.append('【看下来他的性子】')
        lines.extend(observed)

    return '\n'.join(lines)


def _render_observations(slots: dict) -> list[str]:
    """观察类字段。样本不足时它们本来就是 unknown，这里自然不会渲染出来。"""
    out: list[str] = []
    for name in OBSERVABLE_SLOTS:
        slot = slots.get(name)
        if slot and slot['status'] == STATUS_FILLED and slot['value'].strip():
            out.append(f'- {slot_zh(name)}：{slot["value"]}')
    return out
