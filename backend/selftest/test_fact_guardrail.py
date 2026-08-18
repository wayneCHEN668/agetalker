"""事实红线的两个漏洞（第四轮实机测试）。

现场：老人说「今天早晨还没吃饭呢」，AI 回
「……要不要我陪你煮碗热乎的面？就放点青菜，再卧个蛋——**像小时候小华来串门，
你妈总这么给他做**。」

小华确实在台账里（小伙伴，已故，"经常一起玩"）。但"来串门""你妈""总这么给他做"
台账里一个字都没有。这一轮走的是常规路径——事实红线**在场**却没拦住，说明红线
本身有洞：

1. 疑问句漏洞：红线原文把规则写成"陈述句不行，提问可以"，模型就把编的内容挂在
   「要不要我……？」这个问句尾巴上带出来了。判断标准写成了句式，不是断言。
2. 自查是实体级不是命题级：原文让它自查"人名/地点/时间/数字/事件"的来源，
   「小华」一查确实在台账里 → 放行；而"来串门""你妈煮面"既不是人名也不是数字，
   压根不触发自查。台账里有这个人，被当成了台账里有这件事。
"""
import pytest

from prompts.templates import build_normal_prompt, build_crisis_prompt


def _normal() -> str:
    return build_normal_prompt('neutral', {}, memory_context='- 小华（小伙伴，已故）：经常一起玩')


# ─── 漏洞 1：问句不能用来夹带断言 ────────────────────────────────────────────

def test_normal_prompt_closes_the_question_frame_loophole():
    """必须点明：包在问句/提议里的编造，仍然是编造。"""
    prompt = _normal()
    assert '问句' in prompt
    assert '要不要' in prompt          # 现场那个句式被点名了


def test_crisis_prompt_closes_the_question_frame_loophole():
    """危机轮的红线同样不能只管陈述句。"""
    assert '问句' in build_crisis_prompt()


# ─── 漏洞 2：自查要查"说法"，不是查"名字" ────────────────────────────────────

def test_normal_prompt_self_check_is_claim_level():
    """台账里有这个人 ≠ 台账里有这件事，必须写死。"""
    prompt = _normal()
    assert '有这个人' in prompt
    assert '有这件事' in prompt


def test_crisis_prompt_self_check_is_claim_level():
    assert '有这个人' in build_crisis_prompt()
    assert '有这件事' in build_crisis_prompt()


# ─── 现场失败样例要进 prompt ─────────────────────────────────────────────────

def test_normal_prompt_carries_the_field_failure_example():
    """把真实翻车的那一句作为反面例子写进去——抽象规则已经证明拦不住。"""
    prompt = _normal()
    assert '串门' in prompt


def test_field_failure_example_is_marked_as_bad():
    """反面例子必须明确标成"不好"，不能又变成 few-shot 素材（见笔记 9.1）。"""
    prompt = _normal()
    idx = prompt.index('串门')
    # 例子前面 60 字内要出现否定标记
    assert '不好' in prompt[max(0, idx - 60):idx]
