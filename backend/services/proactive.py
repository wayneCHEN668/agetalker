"""主动开口护栏：这一刻该不该出声。

这里的三条规则都不是功能需求，而是"别让这东西变成扰民设备"：

(a) 无人应答的收场。定时招呼时老人很可能不在。连吃 PROACTIVE_NO_ANSWER_GIVEUP
    次闭门羹就当天停手——没有这条，设备会变成定时扰民的喇叭，而且扰的是
    隔壁床的人。
(b) 夜间硬静默窗口。不管作息表怎么配，21:00-07:00 一律不出声。这是防配置
    错误的兜底：daily_routine 是 LLM 从口语里抽的，抽错一个数字就可能变成
    半夜三点自己说话。**采集来的数据不能直接驱动会发出声音的行为。**
(c) 危机警戒期禁止。老人刚经历过危机对话，设备过一会儿自己出声是惊吓，
    不是陪伴。

纯逻辑模块：状态只有内存里的每日计数，可以直接注入时间来测边界值。
"""

import logging
from datetime import datetime, timedelta, timezone

from config import (
    PROACTIVE_MAX_PER_DAY,
    PROACTIVE_NO_ANSWER_GIVEUP,
    PROACTIVE_QUIET_END,
    PROACTIVE_QUIET_START,
)

logger = logging.getLogger(__name__)

_BEIJING = timezone(timedelta(hours=8))


def in_quiet_hours(now: datetime) -> bool:
    """是否处在夜间静默窗口。含起点不含终点：21:00 静默，07:00 解除。"""
    hour = now.hour
    if PROACTIVE_QUIET_START > PROACTIVE_QUIET_END:      # 跨零点，默认情况
        return hour >= PROACTIVE_QUIET_START or hour < PROACTIVE_QUIET_END
    return PROACTIVE_QUIET_START <= hour < PROACTIVE_QUIET_END


class ProactiveGuard:
    """按 elder_id 记当天的主动开口次数与连续无应答次数。

    状态只在内存里，重启即清零——这是有意的：重启后从零开始，最坏情况是
    当天多说几句，比"重启后因为陈旧计数而整天不说话"好。
    """

    def __init__(self):
        self._state: dict[str, dict] = {}

    def _today(self, elder_id: str, now: datetime) -> dict:
        day = now.date().isoformat()
        st = self._state.get(elder_id)
        if st is None or st['date'] != day:
            st = {'date': day, 'count': 0, 'no_answer_streak': 0}
            self._state[elder_id] = st
        return st

    def _ensure_entry(self, elder_id: str, now: datetime) -> dict:
        """惰性创建 elder 的状态，已存在则直接复用——不做跨日归零。

        与 _today() 的区别：_today() 是「读当天配额」的入口，跨天要归零；
        这里只负责保证字典存在，用于记录应答/无应答事件本身不该因为日期
        比对而把刚记的连续无应答次数冲掉。
        """
        st = self._state.get(elder_id)
        if st is None:
            st = {'date': now.date().isoformat(), 'count': 0, 'no_answer_streak': 0}
            self._state[elder_id] = st
        return st

    def can_speak(
        self,
        elder_id: str,
        *,
        crisis_vigilant: bool,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        """能不能主动开口。返回 (可以吗, 不可以的原因)。"""
        now = now or datetime.now(_BEIJING)

        if crisis_vigilant:
            return False, 'crisis_vigilant'
        if in_quiet_hours(now):
            return False, 'quiet_hours'

        st = self._today(elder_id, now)
        if st['count'] >= PROACTIVE_MAX_PER_DAY:
            return False, 'daily_quota'
        if st['no_answer_streak'] >= PROACTIVE_NO_ANSWER_GIVEUP:
            return False, 'no_answer_giveup'
        return True, ''

    def note_spoke(self, elder_id: str, now: datetime | None = None) -> None:
        now = now or datetime.now(_BEIJING)
        self._today(elder_id, now)['count'] += 1

    def note_answered(self, elder_id: str, now: datetime | None = None) -> None:
        """老人应答了，连续无应答清零。"""
        now = now or datetime.now(_BEIJING)
        self._ensure_entry(elder_id, now)['no_answer_streak'] = 0

    def note_no_answer(self, elder_id: str, now: datetime | None = None) -> None:
        now = now or datetime.now(_BEIJING)
        st = self._ensure_entry(elder_id, now)
        st['no_answer_streak'] += 1
        if st['no_answer_streak'] >= PROACTIVE_NO_ANSWER_GIVEUP:
            logger.info(f"连续 {st['no_answer_streak']} 次无人应答，今天不再主动开口 | elder={elder_id}")
