"""时间标签：不许把今天以前的事当成刚刚发生的。

现场：主动招呼里 AI 说「像小时候小华他们跑过墙根」，把六天前记下的往事焊到此刻。
查下来时间信息在三层上全丢了：

1. 对话历史条目只有 {role, content}，没有时间戳；
2. 台账**存了** last_mentioned，render_ledger 渲染时又整个扔掉；
3. 任何 prompt 都没告诉模型今天是几号。

最扎眼的一条现成证据（实盘台账 elder_14j0qmw4）：

    小华 [已故]：…老人今天才知道小华去世了    last_mentioned: 2026-08-13

这条 note 的**文本里**写着「今天」，是 8 月 13 日写下的。模型每天读到的都是
「今天」——小华于是一天天地反复"今天"死。所以光在渲染层补日期救不回旧条目，
必须同时（a）告诉模型方括号里的日期怎么用来兑冲条目内容里的相对词，
（b）从抽取源头禁掉相对词，别让新数据继续被污染。
"""
from datetime import datetime

import pytest

from prompts.templates import (
    build_normal_prompt, build_crisis_prompt,
    build_closing_prompt, build_proactive_prompt,
)
from services.memory_service import EXTRACT_SYSTEM_PROMPT, render_ledger


def _today_zh() -> str:
    now = datetime.now()
    return f"{now.year}年{now.month}月{now.day}日"


LEDGER = {
    'people': [{
        'name': '小华', 'relation': '小伙伴', 'status': '已故',
        'notes': ['经常一起玩', '老人今天才知道小华去世了'],
        'last_mentioned': '2026-08-11T15:41:06.553707+08:00',
    }],
    'events': [{
        'summary': '小时候和小华经常一起玩到很晚',
        'last_mentioned': '2026-08-11T15:41:06.553707+08:00',
    }],
    'preferences': [{
        'content': '喜欢吃热乎汤面',
        'last_mentioned': '2026-08-17T12:44:56.752564+08:00',
    }],
    'session_summaries': [],
}


# ─── 台账每条都要带记录日期 ──────────────────────────────────────────────────

@pytest.mark.parametrize('section', ['people', 'events', 'preferences'])
def test_ledger_entries_carry_their_record_date(section):
    """人物/事件/喜好三节都要带日期。只给其中一节等于没做——
    「小华今天走了」正是挂在 people 的 notes 上。"""
    single = {**{k: [] for k in LEDGER}, section: LEDGER[section]}
    assert '8月11日' in render_ledger(single) or '8月17日' in render_ledger(single)


def test_ledger_explains_how_to_read_the_date():
    """光加日期前缀不够：模型不会自己去把条目里的「今天」换算成那一天。
    必须明说这个兑冲规则，否则旧条目照样被当成刚刚发生。"""
    text = render_ledger(LEDGER)
    assert '今天' in text          # 兑冲说明里必须点名这个词
    assert '不是现在' in text


def test_ledger_stays_empty_when_nothing_recorded():
    """空台账仍然返回空串——别让说明文字把空台账撑成有内容的样子。"""
    assert render_ledger({}) == ''
    assert render_ledger({'people': [], 'events': [], 'preferences': []}) == ''


# ─── 四个 prompt 都要知道今天是几号 ──────────────────────────────────────────

def test_normal_prompt_states_current_date():
    assert _today_zh() in build_normal_prompt('neutral', {})


def test_crisis_prompt_states_current_date():
    assert _today_zh() in build_crisis_prompt()


def test_closing_prompt_states_current_date():
    assert _today_zh() in build_closing_prompt()


def test_proactive_prompt_states_current_date():
    assert _today_zh() in build_proactive_prompt('王爷爷', 'scheduled')


# ─── 抽取源头禁掉相对时间词 ──────────────────────────────────────────────────

def test_extract_prompt_forbids_relative_time_words():
    """新记下的 note 里再写「今天」，就是在给未来的自己埋同一个雷。"""
    assert '今天' in EXTRACT_SYSTEM_PROMPT
    assert '刚才' in EXTRACT_SYSTEM_PROMPT
