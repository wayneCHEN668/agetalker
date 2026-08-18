"""画像 slot 的静态定义：字段清单、采集途径、半衰期、优先级。

为什么单独成模块
----------------
profile_service（状态机）和 elicitation（采集规划器）都要读这份定义。放进
任何一个里，另一个就得反向导入，形成循环依赖。

三类采集途径（设计文档 §3.2）
-----------------------------
只有 askable 需要"找时机问"。这个划分把"何时采集"的问题规模缩小了一半以上：
- askable：老人能自己回答的，对话中引导采集
- observable：性格、情绪基线这类——**永远不问**，从对话行为统计。
  问一个老人"您性格怎么样"本来就是荒谬的。
- external：位置、药名、紧急联系人——由设备/家属/护理员提供，AI 不问。
  本期只占位，由后续立项填入。
"""

ASKABLE    = 'askable'
OBSERVABLE = 'observable'
EXTERNAL   = 'external'

# 半衰期：None 表示永不过期
NEVER = None

# priority 只对 askable 有意义（0 表示不参与排序）。
# 排序依据是"拿到之后能带来什么"，不是字段本身重不重要：
#   1  address    —— 每句话都用得上，且是定时招呼的前置
#   2-3 sensory   —— 唯一能闭环改变系统行为的字段（耳背就调慢 TTS 语速）
#   4  daily_routine —— 决定定时招呼几点开口，不知道就只能瞎猜
#   5  birth_year —— 决定该聊哪个年代的事
SLOTS: dict[str, dict] = {
    # ── 可问的 ──
    'address':            {'kind': ASKABLE, 'halflife_days': NEVER, 'priority': 1,  'zh': '称呼'},
    'sensory_hearing':    {'kind': ASKABLE, 'halflife_days': 180,   'priority': 2,  'zh': '听力'},
    'sensory_vision':     {'kind': ASKABLE, 'halflife_days': 180,   'priority': 3,  'zh': '眼神'},
    'daily_routine':      {'kind': ASKABLE, 'halflife_days': 90,    'priority': 4,  'zh': '作息'},
    'birth_year':         {'kind': ASKABLE, 'halflife_days': NEVER, 'priority': 5,  'zh': '岁数'},
    'chronic_conditions': {'kind': ASKABLE, 'halflife_days': 180,   'priority': 6,  'zh': '老毛病'},
    'medication_times':   {'kind': ASKABLE, 'halflife_days': 180,   'priority': 7,  'zh': '吃药的时间'},
    'sleep':              {'kind': ASKABLE, 'halflife_days': 90,    'priority': 8,  'zh': '睡得好不好'},
    'mobility':           {'kind': ASKABLE, 'halflife_days': 90,    'priority': 9,  'zh': '腿脚方便不方便'},
    'hobbies_current':    {'kind': ASKABLE, 'halflife_days': 180,   'priority': 10, 'zh': '现在爱做什么'},
    'hobbies_past':       {'kind': ASKABLE, 'halflife_days': NEVER, 'priority': 11, 'zh': '以前爱做什么'},
    'occupation':         {'kind': ASKABLE, 'halflife_days': NEVER, 'priority': 12, 'zh': '以前做什么工作'},
    'hometown':           {'kind': ASKABLE, 'halflife_days': NEVER, 'priority': 13, 'zh': '老家'},

    # ── 可观测的（永远不问）──
    'talkativeness':          {'kind': OBSERVABLE, 'halflife_days': NEVER, 'priority': 0, 'zh': '话多话少'},
    'interaction_preference': {'kind': OBSERVABLE, 'halflife_days': NEVER, 'priority': 0, 'zh': '喜欢被问还是自己讲'},
    'taboo_topics':           {'kind': OBSERVABLE, 'halflife_days': NEVER, 'priority': 0, 'zh': '不愿意聊的'},
    'emotional_baseline':     {'kind': OBSERVABLE, 'halflife_days': NEVER, 'priority': 0, 'zh': '情绪底色'},
    'attention_span':         {'kind': OBSERVABLE, 'halflife_days': NEVER, 'priority': 0, 'zh': '能聊多久'},

    # ── 外部录入的（本期只占位）──
    'location':          {'kind': EXTERNAL, 'halflife_days': NEVER, 'priority': 0, 'zh': '位置'},
    'medication_names':  {'kind': EXTERNAL, 'halflife_days': NEVER, 'priority': 0, 'zh': '药名'},
    'emergency_contact': {'kind': EXTERNAL, 'halflife_days': NEVER, 'priority': 0, 'zh': '紧急联系人'},
    'room_number':       {'kind': EXTERNAL, 'halflife_days': NEVER, 'priority': 0, 'zh': '房间号'},
}

ASKABLE_SLOTS    = [k for k, v in SLOTS.items() if v['kind'] == ASKABLE]
OBSERVABLE_SLOTS = [k for k, v in SLOTS.items() if v['kind'] == OBSERVABLE]
EXTERNAL_SLOTS   = [k for k, v in SLOTS.items() if v['kind'] == EXTERNAL]


def is_valid_slot(name: str) -> bool:
    """name 是不是一个已知字段。路由模型返回的 slot_hint 必须先过这一关。"""
    return bool(name) and name in SLOTS


def is_askable(name: str) -> bool:
    """能不能在对话里问这个字段。observable / external 一律不行。"""
    return is_valid_slot(name) and SLOTS[name]['kind'] == ASKABLE


def askable_by_priority() -> list[str]:
    """可问字段按优先级从高到低排序。"""
    return sorted(ASKABLE_SLOTS, key=lambda n: SLOTS[n]['priority'])


def slot_zh(name: str) -> str:
    """字段的中文说法。注入 prompt 时用，绝不能把英文字段名念给老人听。"""
    return SLOTS[name]['zh'] if is_valid_slot(name) else name
