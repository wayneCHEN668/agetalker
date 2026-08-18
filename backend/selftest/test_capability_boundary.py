"""能力边界：蘅小年不能替他做任何实际的事。

现场：老人说「今天早晨还没吃饭呢」，AI 回「要不要我陪你煮碗热乎的面？就放点
青菜，再卧个蛋」。它是个语音陪伴程序——煮不了面、到不了场、递不了东西。

查证下来四个 prompt 里没有任何一处说明它的能力边界，所以这类越界完全不受约束。
10.1 修的是「编人」（我帮你把护工小陈叫过来），这里修的是同一类的另一半：编行动。

已确认的处理方式：**可以提议，但主语必须是老人自己**（行为激活，临床上对食欲
下降和抑郁是有效的），不能是 AI。附带一个硬性门槛——不知道他腿脚方便不方便时，
不许提需要走动的事。
"""
import pytest

from prompts.templates import build_normal_prompt, build_proactive_prompt


def _normal(profile_context: str = '') -> str:
    return build_normal_prompt('neutral', {}, profile_context=profile_context)


def _proactive(profile_context: str = '') -> str:
    return build_proactive_prompt('王爷爷', 'scheduled', profile_context=profile_context)


# ─── 它做不了实际的事 ────────────────────────────────────────────────────────

def test_normal_prompt_states_it_cannot_act_physically():
    assert '做不了' in _normal()


def test_normal_prompt_marks_first_person_offer_as_bad():
    """现场翻车那句要作为反面例子在场，且标成「不好」。"""
    prompt = _normal()
    assert '我陪你煮' in prompt
    idx = prompt.index('我陪你煮')
    assert '不好' in prompt[max(0, idx - 60):idx]


def test_proactive_prompt_states_it_cannot_act_physically():
    """主动开口那条路径同样会提议做点什么，边界必须一样。"""
    assert '做不了' in _proactive()


# ─── 提议的主语必须是老人 ────────────────────────────────────────────────────

def test_normal_prompt_requires_the_elder_as_the_subject():
    prompt = _normal()
    assert '主语' in prompt
    assert '要不要去' in prompt          # 正面例句：他去做，不是 AI 去做


# ─── 腿脚不明时不许提需要走动的事 ────────────────────────────────────────────

def test_normal_prompt_gates_suggestions_on_unknown_mobility():
    """画像里没写腿脚，就不知道他站不站得起来——不许提要走动的事。"""
    prompt = _normal()
    assert '腿脚' in prompt
    assert '走动' in prompt


def test_proactive_prompt_gates_suggestions_on_unknown_mobility():
    assert '腿脚' in _proactive()


# ─── 它感知不到的东西 ────────────────────────────────────────────────────────
# 现场（主动招呼）：「刚才您望着门口那会儿，我瞧见窗台上的光挪了半寸」「今儿风软」。
# 它没有摄像头、看不见他、也没有天气数据。上面那半修的是「编出做不到的动作」，
# 这半修的是「编出感知不到的观察」——同一类问题的第三块。

def test_capability_section_states_it_cannot_perceive():
    """能力边界那段是 normal / proactive 共用的一份，两条路径都得约束到。"""
    for prompt in (_normal(), _proactive()):
        assert '看不见' in prompt
        assert '天气' in prompt


def test_normal_prompt_marks_fabricated_observation_as_bad():
    """现场翻车那句要作为反面例子在场，且标成「不好」。"""
    prompt = _normal()
    assert '我瞧见' in prompt
    idx = prompt.index('我瞧见')
    assert '不好' in prompt[max(0, idx - 80):idx]


def test_proactive_prompt_no_longer_tells_it_to_talk_about_weather():
    """硬规则第 3 条原来写着「就说点眼前的（天气、时候）」——「今儿风软」
    就是这句直接教出来的。天气必须去掉；时候可以留，因为当前时间是真给它的。"""
    assert '（天气、时候）' not in _proactive()


def test_proactive_prompt_requires_memories_be_marked_as_past():
    """「像小时候小华他们跑过墙根」——把台账里的回忆焊到此刻，制造出
    一种它并不在场的亲密感。提以前的事必须说清是以前的。"""
    assert '上回' in _proactive()
