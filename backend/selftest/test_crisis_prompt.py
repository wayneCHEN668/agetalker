"""危机轮不许编人。

现场测试里出现过：老人从没提过女儿、也没提过护工，AI 在危机轮回了
「叫你女儿来陪陪你」「我帮你把护工小陈叫过来」——两个人都是凭空生成的。

根因是危机路径 build_crisis_prompt() 不接任何参数（拿不到画像），prompt 里
却硬性要求「建议联系家人或护工，给个具体的下一步」。手上没有事实又被要求
说具体的，只能编。这批测试锁死修复后的行为。
"""
from unittest.mock import MagicMock, patch

import pytest

from prompts.templates import build_crisis_prompt, CRISIS_VIGILANCE_SECTION
from services.profile_service import (
    empty_profile, mark_filled, render_emergency_contact,
)
from services.llm_service import LLMService


# ─── 紧急联系人的读取 ────────────────────────────────────────────────────────

def test_render_emergency_contact_empty_when_unknown():
    """没录过紧急联系人就是没有，不能给出任何兜底文本。"""
    assert render_emergency_contact(empty_profile('elder_test')) == ''


def test_render_emergency_contact_returns_recorded_value():
    p = empty_profile('elder_test')
    mark_filled(p, 'emergency_contact', '女儿 王丽 138-0000-0000', source='external')
    assert render_emergency_contact(p) == '女儿 王丽 138-0000-0000'


# ─── 危机 prompt：不知道联系人时 ─────────────────────────────────────────────

def test_crisis_prompt_without_contact_asks_instead_of_naming():
    """联系人未知时，落点必须是反过来问他，而不是替他指定一个人。"""
    prompt = build_crisis_prompt()
    assert '你身边现在有人陪你吗' in prompt
    assert '我叫人给你打个电话好不好' in prompt


def test_crisis_prompt_without_contact_forbids_inventing_people():
    """联系人未知时必须显式禁止说出任何具体的人或关系。"""
    prompt = build_crisis_prompt()
    assert '不知道他身边有谁' in prompt
    # 「女儿」「护工」这类称呼只能作为反面例子出现在禁止条款里，
    # 绝不能出现在「该怎么说」的指令里。
    assert '不许' in prompt or '不能' in prompt


def test_crisis_prompt_never_instructs_contacting_relatives_unconditionally():
    """老 prompt 里那条无条件的「建议联系家人或护工」必须已经不在了。"""
    prompt = build_crisis_prompt()
    assert '建议联系家人或护工' not in prompt


# ─── 危机 prompt：知道联系人时 ───────────────────────────────────────────────

def test_crisis_prompt_with_known_contact_names_it():
    """录过紧急联系人，才可以说具体的那一个人。"""
    prompt = build_crisis_prompt(emergency_contact='女儿 王丽 138-0000-0000')
    assert '女儿 王丽 138-0000-0000' in prompt


def test_crisis_prompt_with_known_contact_drops_the_ask_back():
    """知道联系人就不该再反过来问他身边有谁——那等于没记住。"""
    prompt = build_crisis_prompt(emergency_contact='女儿 王丽')
    assert '你身边现在有人陪你吗' not in prompt


# ─── 危机 prompt：画像与事实红线 ─────────────────────────────────────────────

def test_crisis_prompt_carries_profile_context():
    """危机轮是最不能编的一轮，画像必须注入进去。"""
    prompt = build_crisis_prompt(profile_context='- 称呼：王爷爷\n- 慢病：心脏病')
    assert '王爷爷' in prompt
    assert '心脏病' in prompt


def test_crisis_prompt_states_when_profile_is_empty():
    """没有画像时要明说「不了解」，不能留空让模型自行填补。"""
    prompt = build_crisis_prompt()
    assert '还不太了解他的情况' in prompt


def test_crisis_prompt_has_fact_guardrail():
    """常规路径的事实红线在危机路径同样适用，不能只有常规路径有。"""
    prompt = build_crisis_prompt()
    assert '编造' in prompt


# ─── 危机警惕期附加段 ────────────────────────────────────────────────────────

def test_vigilance_section_does_not_name_a_relation():
    """警惕段同样不能替老人指定「家里人或者护工」。"""
    assert '家里人' not in CRISIS_VIGILANCE_SECTION
    assert '护工' not in CRISIS_VIGILANCE_SECTION


# ─── 危机事件要能定位到人 ────────────────────────────────────────────────────

def test_crisis_event_carries_elder_id():
    """管理端拿到告警要能知道是谁——只有 session_id 联系不上老人。"""
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        service = LLMService()

    with patch.object(LLMService, '_write_event', return_value={}) as write:
        service._dispatch_crisis_event('我不想活了', 's_1', 'elder_14j0qmw4')

    event = write.call_args[0][0]
    assert event['elder_id'] == 'elder_14j0qmw4'
    assert event['session_id'] == 's_1'
