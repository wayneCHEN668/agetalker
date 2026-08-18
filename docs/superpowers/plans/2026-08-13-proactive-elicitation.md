# 主动开口引擎 + 画像引导采集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让蘅小年能在恰当的时机主动开口，并在不损害陪伴质量的前提下通过对话自然采集老人画像，且永不重复追问。

**Architecture:** 三层。底层是两个**纯逻辑**模块——`profile_schema.py`（字段定义）和 `elicitation.py`（采集规划器），不调 LLM、不碰 IO，可穷举单测。中层是 `profile_service.py`（slot 状态机 + 存储 + 后台抽取）和 `proactive.py`（主动开口护栏），沿用 `memory_service.py` 已有的「模块级纯函数 + 服务类」结构。上层把它们接进现有的 `llm_service.stream_reply`（消费 router 新增的 `slot_hint`）和新增的 `stream_proactive`，前端加定时器与自动开麦。

**Tech Stack:** Python 3.11 / FastAPI / AsyncOpenAI（Qwen 生成 + DeepSeek 路由抽取）/ pytest；React Native + Expo Router / TypeScript

**Spec:** `docs/superpowers/specs/2026-08-13-proactive-elicitation-design.md`

## Global Constraints

这一节的每一条都隐含在**每个** task 的要求里。

- **一人一设备**（spec §7.4）。`elder_id` 绑定设备，不做身份区分。前端已实现于 `mobile/constants/Session.ts`（localStorage），**本计划不需要新增任务**。
- **采集来的数据不能直接驱动会发出声音的行为**（spec §2）。`daily_routine` 是 LLM 从口语里抽的，有出错率；`PROACTIVE_QUIET_HOURS` 是不受它影响的硬边界。
- **画像是增强能力，失败不影响对话**（spec §9）。抽取/存储/规划任何一处抛异常，都必须记 warning 后让对话照常进行——沿用 `memory_service.py` 既定做法。
- **必须复用现有问句节流器** `LLMService._should_restrain_questions()`（spec §4.2）。禁止另起一套计数。
- **采集不抢 `strategy_id` 的决策权**（spec §4.4）。冲突时策略优先。
- Python 依赖只装在 `backend/.venv/`。
- 测试命令统一用：`cd backend && ./.venv/Scripts/python.exe -m pytest selftest/<file> -q`
- 新代码的注释风格跟随现有模块：中文、解释**为什么**而不是**做了什么**。
- **已知失效的测试**（改动前就是坏的，不要误判成自己弄坏的）：`test_asr.py` / `test_emotion.py` / `test_model.py` / `test_refactor.py::test_config_loading`；`test_ws.py` / `test_tts.py` 连真实服务会挂住。详见 CLAUDE.md。

## 文件结构

**新增（backend）**

| 文件 | 职责 | 纯逻辑 |
|---|---|---|
| `services/profile_schema.py` | slot 清单、采集途径、半衰期、优先级 | 是 |
| `services/profile_service.py` | 状态机纯函数 + `ProfileService`（存储 + 抽取） | 状态机部分是 |
| `services/elicitation.py` | 采集规划器 `plan_elicitation()` | 是 |
| `services/proactive.py` | 主动开口护栏（夜间静默 / 每日上限 / 无人应答） | 是 |
| `selftest/test_profile_schema.py` | | |
| `selftest/test_profile_state.py` | 状态机 + address/birth_year 特殊路径 | |
| `selftest/test_elicitation.py` | 两套门槛穷举 | |
| `selftest/test_proactive.py` | 护栏边界值 | |

**为什么 `profile_schema.py` 单独成文件**（spec §7.1 只列了两个新模块，这是本计划的一个分解决策）：`profile_service`（状态机）和 `elicitation`（规划器）都要读字段定义。放进任一个，另一个就得反向导入，形成循环依赖。

**为什么 `proactive.py` 单独成文件**：spec §10 要求夜间静默窗口和无人应答收场必须有单元测试，但 `LLMService.__init__` 会创建两个 API 客户端，测护栏就得连带 mock 它们。抽成纯函数模块后可直接测。

**修改（backend）**

| 文件 | 改动 |
|---|---|
| `config.py` | 新增 spec §8.4 的 9 组参数 |
| `prompts/templates.py` | router 输出加 `slot_hint`；`NORMAL_SYSTEM_PROMPT` 加 `{elicitation_block}`；新增主动开口 prompt |
| `services/llm_service.py` | `_route_category` 返回值加 `slot_hint`；`stream_reply` 接入规划器；新增 `stream_proactive` |
| `routers/sse_llm.py` | 新增 `POST /llm/proactive` |
| `main.py` | 注入 `ProfileService` |
| `services/tts_service.py` | 读 `sensory_hearing` 调整语速/音量 |

**修改（mobile）**

| 文件 | 改动 |
|---|---|
| `hooks/useLLM.ts` | 新增 `fetchProactive` |
| `app/(tabs)/index.tsx` | 沉默计时器、定时招呼、自动开麦、无人应答收场 |

## 任务依赖顺序

```
Task 1 (config + schema)
   |
Task 2 (状态机纯函数) --> Task 3 (address/birth_year) --> Task 4 (ProfileService 存储)
   |                                                            |
Task 5 (采集规划器) <-------------------------------------------+
   |
Task 6 (router slot_hint) --> Task 7 (prompt 注入 + stream_reply 接线)
   |
Task 8 (画像抽取后台调度) --> Task 9 (观察类字段统计)
   |
Task 10 (主动开口护栏) --> Task 11 (主动开口 prompt + stream_proactive) --> Task 12 (端点 + 注入)
   |
Task 13 (TTS 闭环)
   |
Task 14 (前端 fetchProactive) --> Task 15 (沉默唤起) --> Task 16 (定时招呼 + 无人应答)
```

---

## Task 1: 配置参数 + 画像 schema

**Files:**
- Modify: `backend/config.py`（在 `MEMORY_MAX_SESSION_SUMMARIES` 之后追加新段落）
- Create: `backend/services/profile_schema.py`
- Test: `backend/selftest/test_profile_schema.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `config`: `ELICIT_MAX_PER_SESSION: int`、`ELICIT_COOLDOWN_TURNS: int`、`ELICIT_MAX_ASK_COUNT: int`、`SILENCE_PROMPT_SEC: int`、`PROACTIVE_NO_ANSWER_SEC: int`、`PROACTIVE_NO_ANSWER_GIVEUP: int`、`PROACTIVE_MAX_PER_DAY: int`、`PROACTIVE_QUIET_START: int`、`PROACTIVE_QUIET_END: int`、`OBSERVE_MIN_TURNS: int`、`OBSERVE_MIN_TURNS_EMOTION: int`、`OBSERVE_MIN_SESSIONS: int`、`PROFILE_DIR: str`
  - `profile_schema`: `ASKABLE/OBSERVABLE/EXTERNAL: str`、`NEVER = None`、`SLOTS: dict[str, dict]`、`ASKABLE_SLOTS: list[str]`、`OBSERVABLE_SLOTS: list[str]`、`is_valid_slot(name: str) -> bool`、`is_askable(name: str) -> bool`、`askable_by_priority() -> list[str]`、`slot_zh(name: str) -> str`

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_profile_schema.py`：

```python
"""画像字段定义的静态约束。

这些断言看着琐碎，但它们保护的是两条真实的失败路径：
1. 优先级重复 --> askable_by_priority() 的顺序变成不确定的，"该问哪个"就成了随机
2. 缺 zh --> 注入 prompt 时出现字段英文名，老人会听到"请问您的 sensory_hearing"
"""
import pytest

from services.profile_schema import (
    ASKABLE, OBSERVABLE, EXTERNAL, NEVER, SLOTS,
    ASKABLE_SLOTS, OBSERVABLE_SLOTS,
    is_valid_slot, is_askable, askable_by_priority, slot_zh,
)


def test_every_slot_has_required_keys():
    for name, cfg in SLOTS.items():
        assert cfg['kind'] in (ASKABLE, OBSERVABLE, EXTERNAL), name
        assert 'halflife_days' in cfg, name
        assert cfg['zh'], f'{name} 缺中文名，会把英文字段名念给老人听'


def test_askable_priorities_are_unique_and_positive():
    prios = [SLOTS[n]['priority'] for n in ASKABLE_SLOTS]
    assert len(prios) == len(set(prios)), '优先级重复会让"该问哪个"变成随机'
    assert all(p > 0 for p in prios)


def test_address_is_top_priority():
    # 设计文档 §3.4：称呼每句话都用得上，且是定时招呼的前置
    assert askable_by_priority()[0] == 'address'


def test_never_expiring_slots():
    # 设计文档 §3.6：只有出生年份是真的永不过期
    for name in ('address', 'birth_year', 'hobbies_past', 'occupation', 'hometown'):
        assert SLOTS[name]['halflife_days'] is NEVER, name


def test_observable_slots_are_not_askable():
    # 设计文档 §3.2：性格只能观察，问"您性格怎么样"是荒谬的
    for name in OBSERVABLE_SLOTS:
        assert not is_askable(name), name
    assert 'talkativeness' in OBSERVABLE_SLOTS
    assert 'emotional_baseline' in OBSERVABLE_SLOTS


def test_external_slots_exist_but_are_not_askable():
    # 设计文档 §3.2：本期只占位，由后续立项的家属端填入
    for name in ('location', 'medication_names', 'emergency_contact', 'room_number'):
        assert is_valid_slot(name)
        assert not is_askable(name)


def test_unknown_slot_rejected():
    # 设计文档 §4.1：slot_hint 非法时一律当空，宁可不采
    assert not is_valid_slot('')
    assert not is_valid_slot('favorite_color')
    assert not is_askable('favorite_color')


def test_slot_zh_falls_back_to_name():
    assert slot_zh('address') == '称呼'
    assert slot_zh('favorite_color') == 'favorite_color'
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.profile_schema'`

- [ ] **Step 3: 写 config.py 新增参数**

在 `backend/config.py` 的 `MEMORY_MAX_SESSION_SUMMARIES = 5` 那一行之后追加：

```python
# ── 画像与引导采集（设计文档 2026-08-13）──────────────────────────────────────
# 画像与台账是两个东西：台账是叙事记忆（自由文本、无限增长），画像是结构化
# 状态机（有限字段、能判断"填了没有"）。后者是"不重复询问"的前提。
PROFILE_DIR = os.getenv('PROFILE_DIR', 'data/profiles')

# 一次会话最多主动起几个话头采集。一次对话可能只有 10-20 轮，问 5 条就意味着
# 25% 以上的轮次在采集，老人一定会察觉到味道变了。
# 注意：address 的首次询问不计入这个上限（它不是采集，是自我介绍的一部分）。
ELICIT_MAX_PER_SESSION = 2
# 两次主动采集之间至少隔多少轮，把上面那 2 次撑开到整段对话里
ELICIT_COOLDOWN_TURNS = 5
# 同一个字段问到第几次仍未填上就永久放弃。
# 这是整套机制里最重要的一道硬闸：没有它，"安全窗口""节流"都只是降低频率，
# 一个永远填不上的字段最终一定会被问到第五次、第十次。
ELICIT_MAX_ASK_COUNT = 2

# 观察类字段的最小样本量。样本不足时宁可留空——错误的性格判断会一直影响
# 后续所有对话的语气。
OBSERVE_MIN_TURNS         = 20   # talkativeness / interaction_preference
OBSERVE_MIN_TURNS_EMOTION = 30   # emotional_baseline
OBSERVE_MIN_SESSIONS      = 5    # attention_span

# ── 主动开口 ─────────────────────────────────────────────────────────────────
# 老人开着对话但静默多久之后，AI 先开口。远长于 ASR_SILENCE_FRAMES 的 1.5 秒
# 断句阈值——那个是"这句话说完了没有"，这个是"他是不是不想说了"。
# 量级估计，必须实机调；调错方向时宁可往长了调（被打断的代价大于多等一会儿）。
SILENCE_PROMPT_SEC = 25

# 定时招呼说完后开麦等多久算没人应答。略短于沉默唤起——没人应答时不该比
# 有人时等更久。
PROACTIVE_NO_ANSWER_SEC = 20
# 当天连续几次没人应答就停手。没有这条，设备会变成定时扰民的喇叭，
# 而且扰的是隔壁床的人。
PROACTIVE_NO_ANSWER_GIVEUP = 2
# 当天最多主动招呼几次（早中晚的量级，超过就是打扰）
PROACTIVE_MAX_PER_DAY = 3

# 夜间硬静默窗口（本地时间，含起点不含终点：21:00 <= t 或 t < 07:00 时静默）。
# 这是防配置错误的兜底：daily_routine 是 LLM 从口语里抽的，抽错一个数字就
# 可能变成半夜三点自己说话。采集来的数据不能直接驱动会发出声音的行为。
PROACTIVE_QUIET_START = 21
PROACTIVE_QUIET_END   = 7
```

- [ ] **Step 4: 写 profile_schema.py**

创建 `backend/services/profile_schema.py`：

```python
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
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_schema.py -q`
Expected: PASS，8 passed

- [ ] **Step 6: 确认 config 能导入且没打断现有测试**

Run: `cd backend && ./.venv/Scripts/python.exe -c "import config; print(config.ELICIT_MAX_ASK_COUNT, config.PROACTIVE_QUIET_START, config.PROFILE_DIR)"`
Expected: 输出 `2 21 data/profiles`

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_llm_service.py selftest/test_sentence_merge.py -q`
Expected: PASS（确认新增 config 没影响既有模块）

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/services/profile_schema.py backend/selftest/test_profile_schema.py
git commit -m "feat(profile): 画像字段定义与配置参数

三类采集途径（askable/observable/external），只有第一类需要找时机问。
schema 单独成模块：状态机和采集规划器都要读它，放进任一个会形成循环依赖。"
```

---

## Task 2: Slot 状态机（纯函数）

**Files:**
- Create: `backend/services/profile_service.py`（本任务只写模块级纯函数，`ProfileService` 类在 Task 4）
- Test: `backend/selftest/test_profile_state.py`

**Interfaces:**
- Consumes: `profile_schema.SLOTS / is_valid_slot / NEVER`；`config.ELICIT_MAX_ASK_COUNT`
- Produces:
  - 常量 `STATUS_UNKNOWN / STATUS_ASKED / STATUS_FILLED / STATUS_DECLINED / STATUS_STALE: str`
  - `empty_slot() -> dict`
  - `empty_profile(elder_id: str) -> dict`
  - `mark_asked(profile: dict, slot_name: str, now: datetime | None = None) -> None`
  - `mark_filled(profile: dict, slot_name: str, value: str, source: str = 'conversation', confidence: str = 'high', evidence: str = '', now: datetime | None = None) -> None`
  - `mark_declined(profile: dict, slot_name: str) -> None`
  - `refresh_stale(profile: dict, now: datetime | None = None) -> list[str]`
  - `needs_attention(profile: dict, slot_name: str) -> bool`

**关键语义决定（spec 没写死，本任务定死）：`declined` 只挡「问」，不挡「记」。**
`mark_filled` 从任何状态都能成功，包括 `declined`。理由：老人当初两次没答，后来自己主动说了——当然要记。反过来（记不进去）会导致他明明说了、AI 却装作不知道，比重复问更伤人。

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_profile_state.py`：

```python
"""slot 状态机。这是整套画像机制里最容易出错、也最容易测的部分。"""
from datetime import datetime, timedelta, timezone

import pytest

from services.profile_service import (
    STATUS_UNKNOWN, STATUS_ASKED, STATUS_FILLED, STATUS_DECLINED, STATUS_STALE,
    empty_profile, mark_asked, mark_filled, mark_declined,
    refresh_stale, needs_attention,
)

BJ = timezone(timedelta(hours=8))


def _p():
    return empty_profile('elder_test')


def test_empty_profile_has_every_slot_unknown():
    p = _p()
    assert p['elder_id'] == 'elder_test'
    assert p['slots']['address']['status'] == STATUS_UNKNOWN
    assert p['slots']['address']['ask_count'] == 0
    assert p['slots']['hometown']['value'] == ''


def test_unknown_to_asked_to_filled():
    p = _p()
    mark_asked(p, 'hometown')
    assert p['slots']['hometown']['status'] == STATUS_ASKED
    assert p['slots']['hometown']['ask_count'] == 1
    assert p['slots']['hometown']['last_asked']

    mark_filled(p, 'hometown', '河北保定', evidence='我老家保定的')
    s = p['slots']['hometown']
    assert s['status'] == STATUS_FILLED
    assert s['value'] == '河北保定'
    assert s['source'] == 'conversation'
    assert s['evidence'] == '我老家保定的'
    assert s['last_filled']


def test_second_ask_without_answer_becomes_declined():
    """设计文档 §5.4：沉默即拒绝。

    这是整套机制里最重要的一条硬闸。老人两次都岔开话题，那就是不想说，
    不管他有没有明说出口。
    """
    p = _p()
    mark_asked(p, 'occupation')
    assert p['slots']['occupation']['status'] == STATUS_ASKED
    mark_asked(p, 'occupation')
    assert p['slots']['occupation']['status'] == STATUS_DECLINED
    assert not needs_attention(p, 'occupation')


def test_declined_slot_is_never_asked_again():
    p = _p()
    mark_declined(p, 'sleep')
    before = p['slots']['sleep']['ask_count']
    mark_asked(p, 'sleep')
    assert p['slots']['sleep']['status'] == STATUS_DECLINED
    assert p['slots']['sleep']['ask_count'] == before, 'declined 之后连计数都不该再动'


def test_declined_blocks_asking_but_not_recording():
    """declined 只挡「问」，不挡「记」。

    老人当初两次没答，后来自己主动说了——当然要记。反过来会导致他明明说了、
    AI 却装作不知道，比重复问更伤人。
    """
    p = _p()
    mark_asked(p, 'hobbies_current')
    mark_asked(p, 'hobbies_current')
    assert p['slots']['hobbies_current']['status'] == STATUS_DECLINED

    mark_filled(p, 'hobbies_current', '下象棋')
    assert p['slots']['hobbies_current']['status'] == STATUS_FILLED
    assert p['slots']['hobbies_current']['value'] == '下象棋'


def test_filled_then_asked_again_stays_filled():
    p = _p()
    mark_filled(p, 'hometown', '保定')
    mark_asked(p, 'hometown')
    assert p['slots']['hometown']['status'] == STATUS_FILLED


def test_halflife_turns_filled_into_stale():
    p = _p()
    long_ago = datetime.now(BJ) - timedelta(days=200)
    mark_filled(p, 'hobbies_current', '下象棋', now=long_ago)   # 半衰期 180 天
    changed = refresh_stale(p)
    assert 'hobbies_current' in changed
    assert p['slots']['hobbies_current']['status'] == STATUS_STALE
    assert p['slots']['hobbies_current']['value'] == '下象棋', 'stale 只改状态，不丢值'
    assert needs_attention(p, 'hobbies_current'), 'stale 要能被重新确认'


def test_fresh_filled_does_not_go_stale():
    p = _p()
    mark_filled(p, 'hobbies_current', '下象棋',
                now=datetime.now(BJ) - timedelta(days=10))
    assert refresh_stale(p) == []
    assert p['slots']['hobbies_current']['status'] == STATUS_FILLED


def test_never_expiring_slot_never_goes_stale():
    """设计文档 §3.6：家乡、职业、以前的爱好永不过期。"""
    p = _p()
    ancient = datetime.now(BJ) - timedelta(days=3650)
    for name in ('hometown', 'occupation', 'hobbies_past', 'address', 'birth_year'):
        mark_filled(p, name, 'x', now=ancient)
    assert refresh_stale(p) == []


def test_refresh_stale_ignores_unfilled():
    p = _p()
    mark_asked(p, 'sleep')
    assert refresh_stale(p) == []


def test_needs_attention_matrix():
    p = _p()
    assert needs_attention(p, 'sleep'), 'unknown 需要采'
    mark_asked(p, 'sleep')
    assert needs_attention(p, 'sleep'), 'asked 但没填上，还能再问一次'
    mark_filled(p, 'sleep', '睡得浅')
    assert not needs_attention(p, 'sleep'), 'filled 且没过期，不用再问'


def test_invalid_slot_name_is_ignored_not_raised():
    """采集是增强能力，非法字段名不能把对话搞崩（设计文档 §9）。"""
    p = _p()
    mark_asked(p, 'favorite_color')
    mark_filled(p, 'favorite_color', 'x')
    mark_declined(p, 'favorite_color')
    assert 'favorite_color' not in p['slots']
    assert not needs_attention(p, 'favorite_color')
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.profile_service'`

- [ ] **Step 3: 写状态机纯函数**

创建 `backend/services/profile_service.py`（本任务只写到 `needs_attention` 为止，类在 Task 4 追加）：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_state.py -q`
Expected: PASS，12 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/profile_service.py backend/selftest/test_profile_state.py
git commit -m "feat(profile): slot 状态机

asked 必须是独立于 filled 的状态——只看有没有值，就永远分不清「从没问过」
和「问过但没答上来」，后者会导致无限重复追问。

ask_count>=2 仍未填上即 declined，永不再问。declined 只挡「问」不挡「记」：
老人后来主动说了当然要记。"
```

---

## Task 3: `address` 与 `birth_year` 的特殊路径 + 画像渲染

**Files:**
- Modify: `backend/services/profile_service.py`（在 `needs_attention` 之后追加）
- Modify: `backend/selftest/test_profile_state.py`（追加测试）

**Interfaces:**
- Consumes: Task 2 的全部纯函数；`profile_schema.slot_zh`
- Produces:
  - `DEFAULT_ADDRESS: str`（值为 `'您'`）
  - `render_address(profile: dict) -> str`
  - `set_birth_year(profile: dict, raw_value, source: str = 'conversation', evidence: str = '', now=None) -> bool`
  - `compute_age(profile: dict, today: date | None = None) -> int | None`
  - `render_profile(profile: dict) -> str`

这两个字段各自暴露了一类**失败形式会被集成层吞掉**的问题，所以单独成任务、单独测：
- `address` 缺失时如果渲染成空串，生成出来的是「，上午好啊」这种带空洞的句子——集成测试看不出来，实机才发现。
- `birth_year` 如果存成年龄数字（`83`），一年后就是错的，**且没有任何机制会发现它错了**。

- [ ] **Step 1: 追加失败的测试**

在 `backend/selftest/test_profile_state.py` 末尾追加：

```python
# ─── address / birth_year 特殊路径 ───────────────────────────────────────────

from datetime import date

from services.profile_service import (
    DEFAULT_ADDRESS, render_address, set_birth_year, compute_age, render_profile,
)


def test_address_falls_back_to_nin_when_unknown():
    """设计文档 §3.5：绝不留空、绝不自己编一个称呼。

    这条要单独测，因为它的失败形式是"生成一句带空洞的话"（「，上午好啊」），
    容易在集成层被忽略。
    """
    p = _p()
    assert render_address(p) == DEFAULT_ADDRESS == '您'


def test_address_falls_back_when_declined():
    p = _p()
    mark_asked(p, 'address')
    mark_asked(p, 'address')
    assert p['slots']['address']['status'] == STATUS_DECLINED
    assert render_address(p) == '您'


def test_address_uses_elders_own_words_verbatim():
    """称呼反映身份认同，不规范化、不自作主张加后缀。"""
    p = _p()
    mark_filled(p, 'address', '王老师')
    assert render_address(p) == '王老师'


def test_address_blank_value_still_falls_back():
    p = _p()
    p['slots']['address']['status'] = STATUS_FILLED
    p['slots']['address']['value'] = '   '
    assert render_address(p) == '您'


def test_birth_year_rejects_an_age_number():
    """设计文档 §3.6：存 age: 83 一年后就是错的，且没有机制会发现。"""
    p = _p()
    assert set_birth_year(p, 83) is False
    assert p['slots']['birth_year']['status'] == STATUS_UNKNOWN
    assert compute_age(p) is None


def test_birth_year_accepts_four_digit_year():
    p = _p()
    assert set_birth_year(p, 1943, evidence='我 43 年生的') is True
    assert p['slots']['birth_year']['value'] == '1943'
    assert p['slots']['birth_year']['status'] == STATUS_FILLED


def test_birth_year_accepts_string_and_rejects_garbage():
    p = _p()
    assert set_birth_year(p, ' 1938 ') is True
    assert set_birth_year(p, '属马') is False
    assert set_birth_year(p, '') is False
    assert set_birth_year(p, 2999) is False


def test_age_is_computed_not_stored_and_rolls_over():
    """同一份数据，跨年之后算出来的年龄要 +1。"""
    p = _p()
    set_birth_year(p, 1943)
    assert compute_age(p, today=date(2026, 8, 13)) == 83
    assert compute_age(p, today=date(2027, 1, 1)) == 84
    assert 'age' not in p['slots']['birth_year']


def test_render_profile_empty_returns_empty_string():
    assert render_profile(_p()) == ''


def test_render_profile_only_shows_known_values():
    p = _p()
    mark_filled(p, 'hometown', '河北保定')
    mark_asked(p, 'sleep')            # 问过但没答上，不该出现在渲染里
    text = render_profile(p)
    assert '河北保定' in text
    assert '睡' not in text


def test_render_profile_marks_stale_values():
    """stale 要在 prompt 里标出来，生成侧才知道该用「确认」而不是「陈述」。"""
    p = _p()
    mark_filled(p, 'hobbies_current', '下象棋',
                now=datetime.now(BJ) - timedelta(days=200))
    refresh_stale(p)
    text = render_profile(p)
    assert '下象棋' in text
    assert '可能过时' in text


def test_render_profile_includes_age_not_birth_year():
    p = _p()
    set_birth_year(p, 1943)
    text = render_profile(p)
    assert '1943' not in text, '给模型看年龄，不是出生年份'
    assert '岁' in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_state.py -q`
Expected: FAIL — `ImportError: cannot import name 'DEFAULT_ADDRESS'`

- [ ] **Step 3: 实现**

在 `backend/services/profile_service.py` 的 `needs_attention` 之后追加：

```python
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
```

同时把文件顶部的导入补齐：

```python
from datetime import date, datetime, timedelta, timezone
```

```python
from services.profile_schema import (
    SLOTS, OBSERVABLE_SLOTS, askable_by_priority, is_valid_slot, slot_zh,
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_state.py -q`
Expected: PASS，24 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/profile_service.py backend/selftest/test_profile_state.py
git commit -m "feat(profile): address 兜底与 birth_year 存年份不存年龄

address 未知/被拒绝时一律渲染「您」——失败形式是生成一句带空洞的话
（「，上午好啊」），集成层看不出来，必须单独测。

birth_year 只接受四位年份，拒绝年龄数字：存 age: 83 一年后就是错的，
且没有任何机制会发现。"
```

---

## Task 4: `ProfileService`（存储 + 生命周期）

**Files:**
- Modify: `backend/services/profile_service.py`（在纯函数之后追加类）
- Test: `backend/selftest/test_profile_storage.py`

**Interfaces:**
- Consumes: Task 2/3 的纯函数；`config.PROFILE_DIR`
- Produces:
  - `ProfileService(storage_dir: str = PROFILE_DIR)`
  - `.get_profile(elder_id: str) -> dict`（惰性加载 + 自动 `refresh_stale`）
  - `.get_context(elder_id: str) -> str`（= `render_profile`）
  - `.get_address(elder_id: str) -> str`
  - `.note_asked(elder_id: str, slot_name: str) -> None`（落盘）
  - `.save(elder_id: str) -> None`

沿用 `memory_service.py` 已验证的三条做法：**惰性加载**、**临时文件 + 原子替换**（`tmp.replace(path)`）、**读取时字段补齐**（兼容早期文件）。存储失败一律记 error 后继续——画像是增强能力。

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_profile_storage.py`：

```python
"""画像持久化。存储失败绝不能影响对话（设计文档 §9）。"""
import json
from pathlib import Path

import pytest

from services.profile_service import (
    ProfileService, STATUS_FILLED, mark_filled,
)


@pytest.fixture
def svc(tmp_path):
    return ProfileService(storage_dir=str(tmp_path))


def test_first_access_returns_empty_profile(svc):
    p = svc.get_profile('elder_a')
    assert p['elder_id'] == 'elder_a'
    assert p['slots']['hometown']['status'] == 'unknown'


def test_save_and_reload(svc, tmp_path):
    p = svc.get_profile('elder_a')
    mark_filled(p, 'hometown', '河北保定')
    svc.save('elder_a')

    assert (tmp_path / 'elder_a.json').exists()
    fresh = ProfileService(storage_dir=str(tmp_path))
    assert fresh.get_profile('elder_a')['slots']['hometown']['value'] == '河北保定'


def test_no_temp_file_left_behind(svc, tmp_path):
    p = svc.get_profile('elder_a')
    mark_filled(p, 'hometown', '保定')
    svc.save('elder_a')
    assert list(tmp_path.glob('*.tmp')) == []


def test_corrupted_file_falls_back_to_empty(tmp_path):
    """台账已有此模式：文件坏了按空处理，不能让对话起不来。"""
    (tmp_path / 'elder_b.json').write_text('{ this is not json', encoding='utf-8')
    svc = ProfileService(storage_dir=str(tmp_path))
    p = svc.get_profile('elder_b')
    assert p['slots']['hometown']['status'] == 'unknown'


def test_missing_fields_are_backfilled(tmp_path):
    """早期文件缺字段时补齐，不能 KeyError。"""
    (tmp_path / 'elder_c.json').write_text(
        json.dumps({'elder_id': 'elder_c', 'slots': {
            'hometown': {'value': '保定', 'status': 'filled'}
        }}, ensure_ascii=False),
        encoding='utf-8',
    )
    svc = ProfileService(storage_dir=str(tmp_path))
    p = svc.get_profile('elder_c')
    assert p['slots']['hometown']['value'] == '保定'
    assert p['slots']['hometown']['ask_count'] == 0, '缺的字段要补默认值'
    assert p['slots']['sleep']['status'] == 'unknown', '整个缺的 slot 要补出来'


def test_elder_id_path_traversal_is_sanitized(svc, tmp_path):
    svc.get_profile('../../etc/passwd')
    svc.save('../../etc/passwd')
    written = list(tmp_path.glob('*.json'))
    assert len(written) == 1
    assert '..' not in written[0].name


def test_get_context_and_address(svc):
    p = svc.get_profile('elder_a')
    mark_filled(p, 'address', '王老师')
    mark_filled(p, 'hometown', '保定')
    assert svc.get_address('elder_a') == '王老师'
    assert '保定' in svc.get_context('elder_a')
    assert svc.get_address('elder_unknown') == '您'


def test_note_asked_persists(svc, tmp_path):
    svc.note_asked('elder_a', 'sleep')
    fresh = ProfileService(storage_dir=str(tmp_path))
    assert fresh.get_profile('elder_a')['slots']['sleep']['ask_count'] == 1


def test_save_failure_does_not_raise(svc, monkeypatch):
    """存储失败只记 error，不能把这一轮对话搞崩。"""
    def boom(*a, **k):
        raise OSError('disk full')
    monkeypatch.setattr(Path, 'write_text', boom)
    svc.get_profile('elder_a')
    svc.save('elder_a')          # 不应抛异常
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_storage.py -q`
Expected: FAIL — `ImportError: cannot import name 'ProfileService'`

- [ ] **Step 3: 实现**

在 `backend/services/profile_service.py` 末尾追加：

```python
# ─── 服务 ────────────────────────────────────────────────────────────────────


class ProfileService:
    """画像服务。

    存储独立于台账（独立文件、独立锁）：两者逻辑正交，台账是"合并叙事文本"，
    画像是"状态机推进"。塞进同一个文件就得共享锁，而 memory_service 已经
    440 行，再加一套状态机会让它变成什么都干的模块（设计文档 §7.3）。
    """

    def __init__(self, storage_dir: str = PROFILE_DIR):
        self.storage_dir = Path(storage_dir)
        self._profiles: dict[str, dict] = {}
        logger.info(f"画像服务初始化完成 ✅ (存储目录: {self.storage_dir})")

    # ─── 读取 ───────────────────────────────────────────────────────────

    def get_profile(self, elder_id: str) -> dict:
        """取画像，首次访问时从磁盘惰性加载，并顺手把过期字段转成 stale。"""
        if elder_id not in self._profiles:
            profile = self._load(elder_id)
            if refresh_stale(profile):
                self._save(elder_id, profile)
            self._profiles[elder_id] = profile
        return self._profiles[elder_id]

    def get_context(self, elder_id: str) -> str:
        """注入 system prompt 的画像文本。"""
        return render_profile(self.get_profile(elder_id))

    def get_address(self, elder_id: str) -> str:
        """该怎么称呼他。拿不准一律「您」。"""
        return render_address(self.get_profile(elder_id))

    # ─── 写入 ───────────────────────────────────────────────────────────

    def note_asked(self, elder_id: str, slot_name: str) -> None:
        """记录问过某个字段，并落盘。"""
        profile = self.get_profile(elder_id)
        mark_asked(profile, slot_name)
        self._save(elder_id, profile)

    def save(self, elder_id: str) -> None:
        """把内存里的画像落盘。"""
        if elder_id in self._profiles:
            self._save(elder_id, self._profiles[elder_id])

    # ─── 持久化 ─────────────────────────────────────────────────────────

    def _path(self, elder_id: str) -> Path:
        # elder_id 来自客户端，做一次保守清洗防止路径穿越（沿用台账做法）
        safe = ''.join(c for c in elder_id if c.isalnum() or c in '-_')[:64] or 'unknown'
        return self.storage_dir / f'{safe}.json'

    def _load(self, elder_id: str) -> dict:
        path = self._path(elder_id)
        if not path.exists():
            return empty_profile(elder_id)
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception as e:
            logger.error(f"画像读取失败，按空画像处理 ({path}): {e}")
            return empty_profile(elder_id)

        # 字段补齐：早期文件可能缺 slot、缺 slot 内的键
        base = empty_profile(elder_id)
        for name, slot in (data.get('slots') or {}).items():
            if name in base['slots'] and isinstance(slot, dict):
                base['slots'][name].update(
                    {k: v for k, v in slot.items() if k in base['slots'][name]}
                )
        if isinstance(data.get('observations'), dict):
            base['observations'] = data['observations']
        return base

    def _save(self, elder_id: str, profile: dict) -> None:
        path = self._path(elder_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再替换，避免写到一半被读到半个 JSON
            tmp = path.with_suffix('.json.tmp')
            tmp.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            tmp.replace(path)
        except Exception as e:
            # 画像是增强能力，写不进去也不能影响这一轮对话
            logger.error(f"画像写入失败 ({path}): {e}")
```

同时补齐文件顶部的导入：

```python
import json
from pathlib import Path
from config import ELICIT_MAX_ASK_COUNT, PROFILE_DIR
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_storage.py selftest/test_profile_state.py -q`
Expected: PASS，33 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/profile_service.py backend/selftest/test_profile_storage.py
git commit -m "feat(profile): ProfileService 存储层

独立文件 + 独立锁，不塞进台账：两者逻辑正交，且 memory_service 已经 440 行。
沿用台账已验证的临时文件+原子替换、读取时字段补齐、失败不影响对话。"
```

---

## Task 5: 采集规划器（纯函数，两套门槛）

**Files:**
- Create: `backend/services/elicitation.py`
- Test: `backend/selftest/test_elicitation.py`

**Interfaces:**
- Consumes: `profile_schema.is_askable / askable_by_priority`；`profile_service.needs_attention / STATUS_STALE`；`config.ELICIT_MAX_PER_SESSION / ELICIT_COOLDOWN_TURNS`
- Produces:
  - `MODE_NONE = 'none'` / `MODE_FOLLOW_UP = 'follow_up'` / `MODE_OPEN_TOPIC = 'open_topic'`
  - `ElicitPlan`（`NamedTuple`，字段 `mode: str`、`slot: str`、`is_stale: bool`）
  - `plan_elicitation(profile: dict, *, slot_hint: str, category: str, phase: str, crisis: bool, crisis_vigilant: bool, restrain_questions: bool, turns_since_last_elicit: int, elicited_this_session: int, address_asked_this_session: bool) -> ElicitPlan`

**这是本设计里最容易出错、也最容易测的一段。** 它是纯函数：不调 LLM、不碰 IO，所以 spec §4.2 那两套门槛可以被穷举。

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_elicitation.py`：

```python
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
    """必须复用现有节流器：否则策略问一句、采集问一句，老人体验到连环追问。"""
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_elicitation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.elicitation'`

- [ ] **Step 3: 实现**

创建 `backend/services/elicitation.py`：

```python
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
    if is_askable(slot_hint) and needs_attention(profile, slot_hint):
        return ElicitPlan(MODE_FOLLOW_UP, slot_hint, _is_stale(profile, slot_hint))

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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_elicitation.py -q`
Expected: PASS，26 passed

- [ ] **Step 5: 跑一遍全部离线测试，确认没回归**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_schema.py selftest/test_profile_state.py selftest/test_profile_storage.py selftest/test_elicitation.py selftest/test_llm_service.py selftest/test_sentence_merge.py selftest/test_emotion_refactored.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/elicitation.py backend/selftest/test_elicitation.py
git commit -m "feat(profile): 采集规划器（纯函数，两套门槛）

顺水推舟门槛低、允许在敏感类别下进行——它不改变话题，只是深入老人自己
已经打开的话头。主动起话头门槛高，必须全部安全窗口条件满足。

address 破的是优先级和时机的例（不等线索/冷却/名额），不是安全窗口的例。"
```

---

## Task 6: router 输出新增 `slot_hint`

**Files:**
- Modify: `backend/prompts/templates.py`（`_ROUTER_OUTPUT_FORMAT` 附近）
- Modify: `backend/services/llm_service.py:126-220`（`_route_category`）
- Modify: `backend/selftest/test_llm_service.py`、`backend/selftest/test_long_conversation.py`（**13 处 mock 返回值要一起改**）

**Interfaces:**
- Consumes: `profile_schema.ASKABLE_SLOTS / slot_zh`
- Produces: `templates._build_slot_hint_section() -> str`；`LLMService._route_category(...) -> tuple[str, str, str, str]`（第四个是 `slot_hint`）

**这一步会打破 13 处现有测试。** `_route_category` 现在返回三元组，`test_llm_service.py` 和 `test_long_conversation.py` 里共 13 个 `mock_route.return_value = (...)` 都是三元组。改成四元组后它们全部要跟着改——这是机械改动，但**必须在同一个 commit 里完成**，否则中间状态是红的。

线索检测并进路由调用而不是新开一次 LLM 调用：路由器每轮本来就在跑，加一个输出字段零额外延迟、零额外成本。这不是随手加的——`templates.py` 的 v3 变更记录里，`strategy_id` 就是以同样的理由并进来的。

- [ ] **Step 1: 写失败的测试**

在 `backend/selftest/test_llm_service.py` 末尾追加：

```python
# ─── 路由 slot_hint（画像采集线索）────────────────────────────────────────────

@pytest.mark.asyncio
async def test_route_parses_slot_hint(llm_service):
    """路由在同一次调用里顺带报出采集线索，不新增网络往返。"""
    payload = ('{"category":"neutral","is_crisis":false,"matched_signals":"日常",'
               '"strategy_id":"natural_followup","slot_hint":"sleep"}')
    with patch.object(llm_service.router_client.chat.completions, 'create',
                      new_callable=AsyncMock) as mock_api:
        mock_api.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=payload))]
        )
        category, signals, strategy_id, slot_hint = await llm_service._route_category('昨晚没睡好')
    assert category == 'neutral'
    assert slot_hint == 'sleep'


@pytest.mark.asyncio
async def test_route_drops_invalid_slot_hint(llm_service):
    """设计文档 §4.1：非法字段名一律当空，宁可不采。"""
    payload = ('{"category":"neutral","is_crisis":false,"matched_signals":"",'
               '"strategy_id":"natural_followup","slot_hint":"favorite_color"}')
    with patch.object(llm_service.router_client.chat.completions, 'create',
                      new_callable=AsyncMock) as mock_api:
        mock_api.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=payload))]
        )
        _, _, _, slot_hint = await llm_service._route_category('随便说说')
    assert slot_hint == ''


@pytest.mark.asyncio
async def test_route_missing_slot_hint_is_empty(llm_service):
    """老版本 prompt 或模型漏字段时不能 KeyError。"""
    payload = ('{"category":"neutral","is_crisis":false,"matched_signals":"",'
               '"strategy_id":"natural_followup"}')
    with patch.object(llm_service.router_client.chat.completions, 'create',
                      new_callable=AsyncMock) as mock_api:
        mock_api.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=payload))]
        )
        _, _, _, slot_hint = await llm_service._route_category('随便说说')
    assert slot_hint == ''


@pytest.mark.asyncio
async def test_route_failure_returns_four_tuple(llm_service):
    """降级路径也必须是四元组，否则调用方解包会炸。"""
    with patch.object(llm_service.router_client.chat.completions, 'create',
                      new_callable=AsyncMock) as mock_api:
        mock_api.side_effect = RuntimeError('boom')
        result = await llm_service._route_category('随便说说')
    assert len(result) == 4
    assert result[0] == 'neutral'
    assert result[3] == ''


def test_router_prompt_lists_askable_slots_only():
    """prompt 里的候选字段从 schema 动态生成，不手写第二份（避免两边漂移）。"""
    from prompts.templates import ROUTER_SYSTEM_PROMPT
    assert 'sleep' in ROUTER_SYSTEM_PROMPT
    assert 'hometown' in ROUTER_SYSTEM_PROMPT
    assert 'talkativeness' not in ROUTER_SYSTEM_PROMPT, '观察类字段不该出现在候选里'
    assert 'room_number' not in ROUTER_SYSTEM_PROMPT, '外部录入字段不该出现在候选里'
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_llm_service.py -q -k slot_hint`
Expected: FAIL — 解包报 `ValueError: not enough values to unpack (expected 4, got 3)`

- [ ] **Step 3: 改 templates.py**

在 `backend/prompts/templates.py` 顶部导入区加：

```python
from services.profile_schema import ASKABLE_SLOTS, slot_zh
```

在 `_build_crisis_signal_section()` 之后新增（和它同样的"从单一来源动态生成"套路）：

```python
def _build_slot_hint_section() -> str:
    """生成路由 prompt 里"采集线索"这条规则的候选字段清单。

    清单从 profile_schema.ASKABLE_SLOTS 动态生成，不手写第二份——手写会和
    schema 漂移（schema 加了字段，prompt 不会跟着更新）。这和策略库、危机词表
    的处理方式一致。

    只列 askable：observable 字段（性格、情绪基线）永远不问，external 字段
    （位置、药名）由家属/设备录入，两者都不该出现在候选里。
    """
    items = '、'.join(f'{name}（{slot_zh(name)}）' for name in ASKABLE_SLOTS)
    return (
        '\n## 采集线索（附带判断，不影响上面的类别与策略）\n'
        '老人这句话里，有没有顺带露出下面某个方面的信息？有就把对应的字段名填进 '
        'slot_hint，没有就填空字符串。\n'
        f'候选字段：{items}\n'
        '注意：\n'
        '- 这只是"他提到了这个方面"，不要求他把话说完整。比如"昨晚翻来覆去的"'
        '就算 sleep 的线索。\n'
        '- 拿不准就填空。宁可漏掉，也不要报一个牵强的字段。\n'
        '- 只能填上面列出的字段名，不要自己造新的。\n'
    )
```

把 `_ROUTER_OUTPUT_FORMAT` 改成（新增 `slot_hint` 行）：

```python
_ROUTER_OUTPUT_FORMAT = """\

## 输出格式（控制长度以保证实时性，不要输出多余字段）

只输出一个 JSON 对象，不要任何 markdown 代码块标记、不要任何解释文字：

{
  "category": "depression | anxiety | anger | loneliness | grief | positive | neutral | crisis",
  "is_crisis": true 或 false,
  "matched_signals": "≤15字，简要说明匹配到的信号",
  "strategy_id": "从对应 category 的策略库里选一个 id；is_crisis=true 时留空字符串",
  "slot_hint": "这句话露出线索的字段名；没有就留空字符串"
}
"""
```

找到组装 `ROUTER_SYSTEM_PROMPT` 的那一行（当前形如 `ROUTER_SYSTEM_PROMPT = _ROUTER_BASE_PROMPT + _build_crisis_signal_section() + ... + _ROUTER_OUTPUT_FORMAT`），把 `_build_slot_hint_section()` 插到 `_ROUTER_OUTPUT_FORMAT` **之前**：

```python
ROUTER_SYSTEM_PROMPT = (
    _ROUTER_BASE_PROMPT
    + _build_crisis_signal_section()
    + _build_strategy_menu_section()
    + _build_slot_hint_section()
    + _ROUTER_OUTPUT_FORMAT
)
```

> 实现时以文件里现有的拼接顺序为准，只做"插入一段"这一个改动，不要重排已有片段。

- [ ] **Step 4: 改 `_route_category` 返回四元组**

`backend/services/llm_service.py`：

导入区加：

```python
from services.profile_schema import is_askable
```

把返回类型签名改成 `-> tuple[str, str, str, str]`，并在四个 return 点补上第四个值：

```python
            result = json.loads(raw.strip())
            category = result.get('category', 'neutral')
            is_crisis = result.get('is_crisis', False)
            matched_signals = result.get('matched_signals', '')
            strategy_id = result.get('strategy_id', '')

            # 采集线索：非法字段名一律当空（设计文档 §4.1）。
            # 采集是增强能力，报错的线索宁可丢掉，也不能让它污染这一轮。
            slot_hint = result.get('slot_hint', '') or ''
            if not is_askable(slot_hint):
                slot_hint = ''

            if is_crisis or category == 'crisis':
                return 'crisis', matched_signals, '', ''

            if category not in CATEGORY_STRATEGY_MAP:
                logger.warning(f"路由模型返回未知类别 '{category}'，降级为 neutral")
                return 'neutral', matched_signals, '', slot_hint
```

其余两个 return 点：

```python
            return category, matched_signals, strategy_id, slot_hint
```

```python
        except Exception as e:
            logger.error(f"路由调用失败: {e}，降级为 neutral")
            return 'neutral', '路由暂不可用', '', ''
```

以及空内容那一处：

```python
            if not raw:
                logger.warning("路由调用返回空内容，降级为 neutral")
                return 'neutral', '', '', ''
```

- [ ] **Step 5: 改 `stream_reply` 的解包点**

`backend/services/llm_service.py:455`：

```python
            category, matched_signals, raw_strategy_id, slot_hint = await self._route_category(
                user_text, context, last_category, used_strategies,
                crisis_recent=crisis_vigilant,
                strategy_feedback=strategy_feedback,
            )
```

并在函数开头的默认值区（当前 `strategy_id = ''` 附近）加：

```python
        slot_hint = ''            # 路由未跑（危机命中）时保持空
```

> 本任务只让 `slot_hint` 被解析出来，**先不接采集规划器**（那是 Task 7）。这样这个 commit 是可独立回滚的。

- [ ] **Step 6: 机械迁移 13 处三元组 mock**

Run:

```bash
cd backend && sed -i -E "s/mock_route\.return_value = \(([^)]*)\)/mock_route.return_value = (\1, '')/" selftest/test_llm_service.py selftest/test_long_conversation.py
```

Run: `cd backend && grep -n "mock_route.return_value" selftest/test_llm_service.py selftest/test_long_conversation.py`
Expected: 13 行全部变成四元组，例如 `('neutral', '', 'natural_followup', '')`

- [ ] **Step 7: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_llm_service.py selftest/test_long_conversation.py -q`
Expected: PASS（原有全部 + 新增 5 个）

- [ ] **Step 8: Commit**

```bash
git add backend/prompts/templates.py backend/services/llm_service.py backend/selftest/test_llm_service.py backend/selftest/test_long_conversation.py
git commit -m "feat(profile): router 输出新增 slot_hint

线索检测并进现有路由调用，零额外延迟、零额外成本——沿用 strategy_id 当初
并进来的同一条理由。候选字段从 schema 动态生成，避免和 schema 漂移。

_route_category 改四元组，同步迁移 13 处三元组 mock。"
```

---

## Task 7: 采集指令注入 prompt + `stream_reply` 接线

**Files:**
- Modify: `backend/prompts/templates.py`（`NORMAL_SYSTEM_PROMPT` 加占位符 + 新增 `build_elicitation_block`）
- Modify: `backend/services/llm_service.py`（`_get_session_meta` 加字段；`stream_reply` 调规划器）
- Modify: `backend/main.py`（注入 `ProfileService`）
- Test: `backend/selftest/test_elicitation_wiring.py`

**Interfaces:**
- Consumes: Task 5 的 `plan_elicitation / MODE_*`；Task 4 的 `ProfileService`
- Produces:
  - `templates.build_elicitation_block(mode: str, slot_name: str, is_stale: bool) -> str`
  - `build_normal_prompt(..., elicitation_block: str = '')`（新增关键字参数，默认空串保持向后兼容）
  - `LLMService.__init__(memory_service=None, profile_service=None)`
  - session_meta 新增键：`elicited_count: int`、`last_elicit_turn: int`、`address_asked: bool`

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_elicitation_wiring.py`：

```python
"""采集指令怎么进到 prompt 里，以及会话级计数器怎么推进。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from prompts.templates import build_elicitation_block, build_normal_prompt
from services.elicitation import MODE_NONE, MODE_FOLLOW_UP, MODE_OPEN_TOPIC

EMOTION = {'label': 'neutral', 'label_zh': '平静', 'score': 0.9,
           'valence': 0.5, 'arousal': 0.2, 'trend': '首次对话'}


def test_block_none_tells_model_to_just_chat():
    text = build_elicitation_block(MODE_NONE, '', False)
    assert '正常聊' in text


def test_follow_up_block_forbids_changing_topic():
    text = build_elicitation_block(MODE_FOLLOW_UP, 'sleep', False)
    assert '睡得好不好' in text, '必须用中文说法，不能把英文字段名念出来'
    assert '不要转移话题' in text


def test_open_topic_block_uses_chinese_name():
    text = build_elicitation_block(MODE_OPEN_TOPIC, 'hometown', False)
    assert '老家' in text
    assert 'hometown' not in text


def test_stale_block_says_confirm_not_ask():
    """设计文档 §5.5：确认已知信息是亲近的表现，重新提问是疏远的表现。"""
    text = build_elicitation_block(MODE_OPEN_TOPIC, 'hobbies_current', True)
    assert '确认' in text
    assert '以前记过' in text


def test_address_block_is_natural_not_interrogative():
    text = build_elicitation_block(MODE_OPEN_TOPIC, 'address', False)
    assert '称呼' in text


def test_normal_prompt_embeds_elicitation_block():
    block = build_elicitation_block(MODE_OPEN_TOPIC, 'hometown', False)
    prompt = build_normal_prompt('neutral', EMOTION, elicitation_block=block)
    assert '老家' in prompt


def test_normal_prompt_without_block_still_builds():
    """默认空串，老调用方不受影响。"""
    prompt = build_normal_prompt('neutral', EMOTION)
    assert '蘅小年' in prompt


@pytest.fixture
def svc(tmp_path):
    from services.llm_service import LLMService
    from services.profile_service import ProfileService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch.object(LLMService, '_write_event', return_value={}):
            yield LLMService(profile_service=ProfileService(storage_dir=str(tmp_path)))


def _stream(chunks):
    async def gen():
        for c in chunks:
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=c))])
    m = AsyncMock()
    m.__aiter__ = lambda self: gen()
    return m


@pytest.mark.asyncio
async def test_first_turn_asks_address_and_marks_it(svc):
    """第一次会话开场就问称呼，且记进画像（设计文档 §3.5）。"""
    with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '', 'natural_followup', '')
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _stream(['你好啊。'])
            async for _ in svc.stream_reply('你好', EMOTION, 's1', 'e1'):
                pass

    profile = svc.profile.get_profile('e1')
    assert profile['slots']['address']['ask_count'] == 1
    assert svc._get_session_meta('s1')['address_asked'] is True


@pytest.mark.asyncio
async def test_address_not_reasked_next_turn(svc):
    with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '', 'natural_followup', '')
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _stream(['嗯。'])
            for _ in range(3):
                mock_create.return_value = _stream(['嗯。'])
                async for _ in svc.stream_reply('随便说说', EMOTION, 's1', 'e1'):
                    pass

    assert svc.profile.get_profile('e1')['slots']['address']['ask_count'] == 1


@pytest.mark.asyncio
async def test_crisis_turn_never_elicits(svc):
    """危机轮两种采集都硬禁止。"""
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as mock_create:
        mock_create.return_value = _stream(['我听到了。'])
        async for _ in svc.stream_reply('我不想活了', EMOTION, 's2', 'e2'):
            pass

    profile = svc.profile.get_profile('e2')
    assert all(s['ask_count'] == 0 for s in profile['slots'].values())


@pytest.mark.asyncio
async def test_service_works_without_profile_service():
    """画像是增强能力，没有它对话照常（和 memory 一样的原则）。"""
    from services.llm_service import LLMService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        svc = LLMService(profile_service=None)
        with patch.object(svc, '_route_category', new_callable=AsyncMock) as mock_route:
            mock_route.return_value = ('neutral', '', 'natural_followup', '')
            with patch.object(svc.client.chat.completions, 'create',
                              new_callable=AsyncMock) as mock_create:
                mock_create.return_value = _stream(['嗯。'])
                events = [e async for e in svc.stream_reply('你好', EMOTION, 's3', 'e3')]
    assert any(e['type'] == 'done' for e in events)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_elicitation_wiring.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_elicitation_block'`

- [ ] **Step 3: 加 `build_elicitation_block`**

在 `backend/prompts/templates.py` 的 `build_pacing_block` 之后追加：

```python
# ─── 画像引导采集 ────────────────────────────────────────────────────────────
# 采集不抢策略的决策权（设计文档 §4.4）：策略仍然决定这一轮 AI 要做什么，
# 这一段只是追加一句"顺带关心一下 X"。冲突时策略优先。

def build_elicitation_block(mode: str, slot_name: str, is_stale: bool) -> str:
    """把采集规划器的决策翻译成给生成模型看的一句话。"""
    if mode == 'none' or not slot_name:
        return '（这一轮没什么要打听的，正常聊就行。）'

    zh = slot_zh(slot_name)

    if mode == 'follow_up':
        return (
            f'他刚才的话里顺带提到了「{zh}」。顺着他自己开的这个话头，自然地多'
            f'关心一句就行——**不要转移话题**，不要连着追问，一句就够。'
        )

    if is_stale:
        return (
            f'「{zh}」这件事以前记过，但有段时间了，可能过时了。找个自然的地方'
            f'用**确认**的语气顺口问一下（比如「您那个……这阵子还……不」），'
            f'不要当成头一回问——把人当陌生人重新问一遍，他会觉得你把他忘了。'
        )

    if slot_name == 'address':
        return (
            '你还不知道该怎么称呼他。找个自然的地方问一句（比如「我该怎么称呼您'
            '呀」）。这不是查户口——不知道怎么称呼就聊天本来才是失礼。'
            '他说什么就是什么，别自作主张给他加「阿姨」「大爷」这种后缀。'
        )

    return (
        f'如果这一轮有自然的地方，可以从「{zh}」轻轻起个话头，了解一下。'
        f'**只是顺口一提，不要盘问**；他要是没接这个茬，就顺着他说的走，别追。'
    )
```

- [ ] **Step 4: 给 `NORMAL_SYSTEM_PROMPT` 加占位符**

在 `NORMAL_SYSTEM_PROMPT` 里，紧跟「## 这次聊天的节奏」那一段之后插入：

```
## 这一轮顺带留意的
{elicitation_block}
```

并在 `build_normal_prompt` 的签名末尾加参数、在 `.format(...)` 里加对应键：

```python
def build_normal_prompt(
    category: str,
    emotion: dict,
    matched_signals: str = "",
    strategy_id: str = "",
    crisis_vigilant: bool = False,
    memory_context: str = "",
    session_summary: str = "",
    phase: str = "deepening",
    restrain_questions: bool = False,
    profile_context: str = "",
    elicitation_block: str = "",
) -> str:
```

```python
        pacing_block            = build_pacing_block(phase, restrain_questions),
        profile_block           = profile_context or "（还不太了解他的情况。）",
        elicitation_block       = elicitation_block or "（这一轮没什么要打听的，正常聊就行。）",
```

同时在「## 你已经知道的事」之后插入画像段：

```
## 你了解的他这个人
{profile_block}
```

- [ ] **Step 5: 接线 `stream_reply`**

`backend/services/llm_service.py`：

导入区加：

```python
from services.elicitation import MODE_NONE, plan_elicitation
from prompts.templates import build_elicitation_block
```

`__init__` 签名与赋值：

```python
    def __init__(self, memory_service=None, profile_service=None):
        self.memory = memory_service
        # 画像服务。为 None 时整套采集逻辑静默跳过，对话照常工作——
        # 和记忆一样，画像是增强能力，不是对话的前置依赖。
        self.profile = profile_service
```

`_get_session_meta` 的初始化字典加三个键：

```python
            self.session_meta[session_id] = {
                'started_at': datetime.now(timezone.utc),
                'turn_count': 0,
                'consecutive_questions': 0,
                # ── 采集节奏（设计文档 §4.2/§4.3）──
                'elicited_count': 0,      # 本会话已主动起了几个话头（不含 address）
                'last_elicit_turn': -999, # 上次主动采集在第几轮，用于冷却
                'address_asked': False,   # 本会话是否已问过称呼
            }
```

在「步骤 4：构建 System Prompt」**之前**插入采集决策：

```python
        # ── 步骤 3.6：采集规划（纯逻辑，不调 LLM）─────────────────────────────
        meta = self._get_session_meta(session_id)
        elicit_block = ''
        plan = None
        if self.profile is not None:
            try:
                plan = plan_elicitation(
                    self.profile.get_profile(elder_id),
                    slot_hint                  = slot_hint,
                    category                   = category,
                    phase                      = self.get_phase(session_id),
                    crisis                     = crisis,
                    crisis_vigilant            = crisis_vigilant,
                    restrain_questions         = self._should_restrain_questions(session_id),
                    turns_since_last_elicit    = meta['turn_count'] - meta['last_elicit_turn'],
                    elicited_this_session      = meta['elicited_count'],
                    address_asked_this_session = meta['address_asked'],
                )
                if plan.mode != MODE_NONE:
                    elicit_block = build_elicitation_block(plan.mode, plan.slot, plan.is_stale)
            except Exception as e:
                # 采集失败不影响对话（设计文档 §9）
                logger.warning(f"采集规划失败（忽略，不影响对话）: {e}")
                plan = None
```

把 `build_normal_prompt(...)` 调用补两个参数：

```python
                profile_context   = self.profile.get_context(elder_id) if self.profile else '',
                elicitation_block = elicit_block,
```

在「步骤 10：保存助手回复」之后、`turn_count += 1` 之后追加计数推进：

```python
        # ── 步骤 10.4：推进采集计数（问出去了才算，规划器只是打算）──────────────
        if plan is not None and plan.mode != MODE_NONE and self.profile is not None:
            try:
                self.profile.note_asked(elder_id, plan.slot)
                if plan.slot == 'address':
                    # address 不计入会话名额：它不是采集，是自我介绍的一部分
                    meta['address_asked'] = True
                else:
                    meta['elicited_count'] += 1
                    meta['last_elicit_turn'] = meta['turn_count']
            except Exception as e:
                logger.warning(f"采集计数推进失败（忽略）: {e}")
```

- [ ] **Step 6: 注入 ProfileService**

`backend/main.py`：

```python
from services.profile_service import ProfileService
```

```python
    profile_svc = ProfileService() if MEMORY_ENABLED else None
    llm_svc = LLMService(memory_service=memory_svc, profile_service=profile_svc)
```

> 复用 `MEMORY_ENABLED` 开关：画像和台账是同一类「增强能力」，运维上没有分开开关的理由，多一个开关只会多一种没人测过的组合。

- [ ] **Step 7: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_elicitation_wiring.py selftest/test_llm_service.py selftest/test_long_conversation.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/prompts/templates.py backend/services/llm_service.py backend/main.py backend/selftest/test_elicitation_wiring.py
git commit -m "feat(profile): 采集指令注入 prompt，接进 stream_reply

采集不抢 strategy_id 的决策权，只在 prompt 里追加一句「顺带关心一下 X」。
stale 走确认话术而非重新提问——把人当陌生人重新问一遍，他会觉得你把他忘了。
profile_service 为 None 时整套逻辑静默跳过，对话照常。"
```

---

## Task 8: 画像抽取（后台异步）

**Files:**
- Modify: `backend/services/profile_service.py`（新增抽取 prompt + `observe_turn`）
- Modify: `backend/services/llm_service.py`（`_schedule_memory_work` 里多派一个后台任务）
- Test: `backend/selftest/test_profile_extract.py`

**Interfaces:**
- Consumes: Task 4 的 `ProfileService`；`config.DEEPSEEK_*` / `ROUTER_EXTRA_BODY`
- Produces:
  - `profile_service.PROFILE_EXTRACT_SYSTEM_PROMPT: str`
  - `ProfileService.observe_turn(elder_id: str, user_text: str) -> dict`（async，返回抽到的 `{slot: value}`）

**为什么是独立的一次调用**（spec §8.3）：ProfileService 自己发一次后台抽取，与 `memory_service._extract_facts` 并行。两个服务完全解耦、各自可独立测试与失败。代价是老人每句话触发两次后台 LLM 调用（一小时 120 轮 = 240 次）。两者都在后台、不占关键路径。成本或速率限制成为问题时再合并，符合 YAGNI。

**只从老人原话抽，绝不从 AI 回复抽**——沿用台账最重要的那条约束。AI 回复可能含幻觉，把它当事实写进画像等于把幻觉洗成"记忆"。

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_profile_extract.py`：

```python
"""画像抽取。抽取失败绝不能影响对话。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.profile_service import ProfileService, PROFILE_EXTRACT_SYSTEM_PROMPT


@pytest.fixture
def svc(tmp_path):
    with patch('services.profile_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        yield ProfileService(storage_dir=str(tmp_path))


def _reply(payload: dict):
    return MagicMock(choices=[MagicMock(message=MagicMock(
        content=json.dumps(payload, ensure_ascii=False)))])


def test_prompt_lists_only_askable_slots():
    assert 'hometown' in PROFILE_EXTRACT_SYSTEM_PROMPT
    assert 'talkativeness' not in PROFILE_EXTRACT_SYSTEM_PROMPT
    assert '不要推测' in PROFILE_EXTRACT_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_extract_fills_slots(svc):
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _reply({'hometown': '河北保定', 'occupation': '小学老师'})
        got = await svc.observe_turn('e1', '我老家保定的，以前教小学')

    assert got['hometown'] == '河北保定'
    p = svc.get_profile('e1')
    assert p['slots']['hometown']['value'] == '河北保定'
    assert p['slots']['hometown']['status'] == 'filled'
    assert p['slots']['hometown']['evidence'], '来源要留痕，支撑将来的导出'


@pytest.mark.asyncio
async def test_extract_routes_birth_year_through_validator(svc):
    """抽到年龄数字要被拒（设计文档 §3.6）。"""
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _reply({'birth_year': '83'})
        await svc.observe_turn('e1', '我今年八十三了')
    assert svc.get_profile('e1')['slots']['birth_year']['status'] == 'unknown'

    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _reply({'birth_year': '1943'})
        await svc.observe_turn('e1', '我 43 年生的')
    assert svc.get_profile('e1')['slots']['birth_year']['value'] == '1943'


@pytest.mark.asyncio
async def test_extract_ignores_unknown_and_non_askable_keys(svc):
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _reply({
            'favorite_color': '蓝色',
            'talkativeness': '话多',
            'location': '北京',
        })
        got = await svc.observe_turn('e1', '随便说说')
    assert got == {}


@pytest.mark.asyncio
async def test_extract_failure_is_swallowed(svc):
    """抽取失败只记 warning，不能抛到调用方（设计文档 §9）。"""
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.side_effect = RuntimeError('api down')
        got = await svc.observe_turn('e1', '我老家保定的')
    assert got == {}


@pytest.mark.asyncio
async def test_extract_skips_blank_text(svc):
    assert await svc.observe_turn('e1', '   ') == {}


@pytest.mark.asyncio
async def test_extract_persists_to_disk(svc, tmp_path):
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _reply({'hometown': '保定'})
        await svc.observe_turn('e1', '我老家保定的')

    fresh = ProfileService(storage_dir=str(tmp_path))
    assert fresh.get_profile('e1')['slots']['hometown']['value'] == '保定'
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_extract.py -q`
Expected: FAIL — `ImportError: cannot import name 'PROFILE_EXTRACT_SYSTEM_PROMPT'`

- [ ] **Step 3: 实现抽取**

在 `backend/services/profile_service.py` 的纯函数区之后、`ProfileService` 类之前追加：

```python
# ─── 抽取 prompt ─────────────────────────────────────────────────────────────

def _build_extract_prompt() -> str:
    """从 schema 动态生成候选字段清单，不手写第二份。"""
    lines = '\n'.join(
        f'- {name}：{slot_zh(name)}' for name in ASKABLE_SLOTS
    )
    return f"""\
你是老年人陪伴系统的「画像抽取」模块。从老人刚说的这句话里，抽出下面这些方面的
信息，输出 JSON。

## 最重要的规则
只抽取老人**自己说出来的**内容。绝对不要推测、不要补全、不要把常识当事实。
- 老人说「我老家保定的」→ 可以记 hometown: 河北保定
- 老人说「我老家保定的」→ 不能记 hometown 之外的任何字段
宁可少记，不能记错。记错了会在后面的对话里被当成真事反复引用，比没记更糟。

## 可以抽的字段
{lines}

## 特别说明
- birth_year 只填**四位出生年份**。老人说"我今年八十三了"时，如果你能从对话里
  确定当前年份就换算成出生年份；换算不确定就留空，不要填年龄数字。
- medication_times 只记**什么时候吃**，不要记剂量。
- address 是他希望**别人怎么称呼他**（「王老师」「老王」「翠芬」都行），
  照他自己说的写，不要加「阿姨」「大爷」这种后缀。

## 输出格式
只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释。只放这句话里真的
提到了的字段，其他字段不要出现：

{{"hometown": "河北保定"}}

这句话里没有值得记的，就输出 {{}}。这是很常见的情况，不要硬凑。
"""


PROFILE_EXTRACT_SYSTEM_PROMPT = _build_extract_prompt()
```

在 `ProfileService.__init__` 里加抽取客户端（和 memory_service 一样用轻量模型）：

```python
        # 抽取用轻量模型，与主生成模型完全分离
        self.client = AsyncOpenAI(
            api_key  = DEEPSEEK_API_KEY,
            base_url = DEEPSEEK_BASE_URL,
        )
```

在 `ProfileService` 里追加：

```python
    async def observe_turn(self, elder_id: str, user_text: str) -> dict:
        """从老人这一句话里抽画像字段，合并进画像并落盘。

        只传 user_text——不传 AI 的回复。AI 回复是生成出来的，可能含幻觉，
        把它当事实写进画像等于把幻觉洗成记忆（沿用台账最重要的那条约束）。
        """
        if not user_text.strip():
            return {}

        raw = await self._extract(user_text)
        if not raw:
            return {}

        profile = self.get_profile(elder_id)
        applied: dict = {}
        for name, value in raw.items():
            if not is_askable(name) or not str(value).strip():
                continue
            if name == 'birth_year':
                # 走校验器，拒绝年龄数字
                if set_birth_year(profile, value, evidence=user_text[:60]):
                    applied[name] = str(value).strip()
                continue
            mark_filled(profile, name, str(value), evidence=user_text[:60])
            applied[name] = str(value).strip()

        if applied:
            self._save(elder_id, profile)
            logger.info(f"画像更新 | elder={elder_id} | {list(applied)}")
        return applied

    async def _extract(self, user_text: str) -> dict:
        try:
            resp = await self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {'role': 'system', 'content': PROFILE_EXTRACT_SYSTEM_PROMPT},
                    {'role': 'user',   'content': f'老人说：「{user_text}」'},
                ],
                temperature=0.0,
                max_tokens=300,
                response_format={'type': 'json_object'},
                extra_body=ROUTER_EXTRA_BODY,
            )
            raw = resp.choices[0].message.content
            data = json.loads(raw.strip()) if raw else {}
            return data if isinstance(data, dict) else {}
        except Exception as e:
            # 画像是增强能力，抽取失败不该影响对话本身
            logger.warning(f"画像抽取失败（忽略，不影响对话）: {e}")
            return {}
```

补齐导入：

```python
from openai import AsyncOpenAI
from config import (
    ELICIT_MAX_ASK_COUNT, PROFILE_DIR,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, ROUTER_EXTRA_BODY,
)
from services.profile_schema import (
    SLOTS, ASKABLE_SLOTS, OBSERVABLE_SLOTS,
    askable_by_priority, is_askable, is_valid_slot, slot_zh,
)
```

- [ ] **Step 4: 挂到后台调度**

`backend/services/llm_service.py` 的 `_schedule_memory_work`，在派发记忆任务的同一处追加：

```python
        # 画像抽取：和记忆抽取并行的独立后台调用。两个服务解耦，各自可独立失败。
        # 都在后台，不占关键路径——本轮回复的延迟完全不受影响。
        if self.profile is not None and not crisis and user_text.strip():
            self._spawn_bg(self.profile.observe_turn(elder_id, user_text))
```

> 危机轮不抽画像：那一轮的全部注意力都该在危机处理上，而且危机语境下的话不适合当画像素材。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_extract.py selftest/test_elicitation_wiring.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/profile_service.py backend/services/llm_service.py backend/selftest/test_profile_extract.py
git commit -m "feat(profile): 后台画像抽取

只从老人原话抽，绝不从 AI 回复抽——沿用台账最重要的那条约束，
把 AI 回复当事实写进画像等于把幻觉洗成记忆。

独立于记忆抽取的一次调用：两个服务解耦、各自可独立失败。都在后台，
不占关键路径。成本成为问题时再合并（YAGNI）。"
```

---

## Task 9: 观察类字段统计

**Files:**
- Modify: `backend/services/profile_service.py`（新增 `observe_behavior`）
- Modify: `backend/services/llm_service.py`（每轮调用）
- Test: `backend/selftest/test_profile_observe.py`

**Interfaces:**
- Consumes: `config.OBSERVE_MIN_TURNS / OBSERVE_MIN_TURNS_EMOTION`
- Produces: `ProfileService.observe_behavior(elder_id: str, user_text: str, category: str, ai_asked_question: bool) -> None`

**样本不足时宁可留空**：错误的性格判断会一直影响后续所有对话的语气。这条比"尽快得出结论"重要得多。

`emotional_baseline` 所需的数据现有系统每轮都在产出（router 的 `category`），只是从没被统计过。

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_profile_observe.py`：

```python
"""观察类字段：永远不问，从对话行为统计。"""
import pytest
from unittest.mock import MagicMock, patch

from services.profile_service import ProfileService, STATUS_FILLED, STATUS_UNKNOWN


@pytest.fixture
def svc(tmp_path):
    with patch('services.profile_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        yield ProfileService(storage_dir=str(tmp_path))


def _feed(svc, n, text='还行吧', category='neutral', asked=False):
    for _ in range(n):
        svc.observe_behavior('e1', text, category, asked)


def test_below_min_sample_stays_unknown(svc):
    """设计文档 §3.2：样本不足时宁可留空。"""
    _feed(svc, 19)
    p = svc.get_profile('e1')
    assert p['slots']['talkativeness']['status'] == STATUS_UNKNOWN


def test_talkativeness_short_answers(svc):
    _feed(svc, 20, text='嗯')
    slot = svc.get_profile('e1')['slots']['talkativeness']
    assert slot['status'] == STATUS_FILLED
    assert '话少' in slot['value']
    assert slot['source'] == 'observed'


def test_talkativeness_long_answers(svc):
    _feed(svc, 20, text='那可说来话长了，' * 8)
    assert '话多' in svc.get_profile('e1')['slots']['talkativeness']['value']


def test_emotional_baseline_needs_more_samples(svc):
    _feed(svc, 25, category='depression')
    assert svc.get_profile('e1')['slots']['emotional_baseline']['status'] == STATUS_UNKNOWN
    _feed(svc, 5, category='depression')
    slot = svc.get_profile('e1')['slots']['emotional_baseline']
    assert slot['status'] == STATUS_FILLED
    assert '抑郁' in slot['value']


def test_emotional_baseline_ignores_neutral_only(svc):
    """全程中性说明没有明显底色，不该硬扣一顶帽子。"""
    _feed(svc, 40, category='neutral')
    assert svc.get_profile('e1')['slots']['emotional_baseline']['status'] == STATUS_UNKNOWN


def test_interaction_preference_prefers_talking_freely(svc):
    for _ in range(20):
        svc.observe_behavior('e1', '嗯', 'neutral', True)        # 被问之后话短
    for _ in range(20):
        svc.observe_behavior('e1', '那可有的说了，' * 6, 'neutral', False)  # 自己讲时话长
    slot = svc.get_profile('e1')['slots']['interaction_preference']
    assert slot['status'] == STATUS_FILLED
    assert '自己讲' in slot['value']


def test_observations_persist(svc, tmp_path):
    _feed(svc, 20, text='嗯')
    fresh = ProfileService(storage_dir=str(tmp_path))
    assert fresh.get_profile('e1')['slots']['talkativeness']['status'] == STATUS_FILLED


def test_observe_never_marks_observable_as_askable(svc):
    """观察类字段没有 asked 状态（设计文档 §5.6）。"""
    _feed(svc, 20, text='嗯')
    assert svc.get_profile('e1')['slots']['talkativeness']['ask_count'] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_observe.py -q`
Expected: FAIL — `AttributeError: 'ProfileService' object has no attribute 'observe_behavior'`

- [ ] **Step 3: 实现**

在 `ProfileService` 里追加：

```python
    # ─── 观察类字段（永远不问，从对话行为统计）────────────────────────────

    def observe_behavior(
        self,
        elder_id: str,
        user_text: str,
        category: str,
        ai_asked_question: bool,
    ) -> None:
        """累计一轮的行为观测，够样本了就下结论。

        样本不足时宁可留空（设计文档 §3.2）——错误的性格判断会一直影响后续
        所有对话的语气，比"暂时不知道"糟糕得多。

        同步方法：只做计数和阈值判断，不调 LLM、不做 IO 密集操作。
        """
        if not user_text.strip():
            return
        profile = self.get_profile(elder_id)
        obs = profile.setdefault('observations', {})

        obs['turns'] = obs.get('turns', 0) + 1
        obs['chars'] = obs.get('chars', 0) + len(user_text.strip())
        if ai_asked_question:
            obs['after_q_turns'] = obs.get('after_q_turns', 0) + 1
            obs['after_q_chars'] = obs.get('after_q_chars', 0) + len(user_text.strip())
        else:
            obs['free_turns'] = obs.get('free_turns', 0) + 1
            obs['free_chars'] = obs.get('free_chars', 0) + len(user_text.strip())
        cats = obs.setdefault('categories', {})
        cats[category] = cats.get(category, 0) + 1

        self._settle_observations(profile, obs)
        self._save(elder_id, profile)

    @staticmethod
    def _settle_observations(profile: dict, obs: dict) -> None:
        turns = obs.get('turns', 0)

        # ── 话多话少 ──
        if turns >= OBSERVE_MIN_TURNS:
            avg = obs['chars'] / turns
            verdict = '话少，答得短，别追着问' if avg < 10 else (
                '话多，愿意讲，给他讲完的空间' if avg > 40 else '不多不少')
            mark_filled(profile, 'talkativeness', verdict,
                        source='observed', confidence='low')

        # ── 喜欢被问还是自己讲 ──
        aq, fq = obs.get('after_q_turns', 0), obs.get('free_turns', 0)
        if aq >= OBSERVE_MIN_TURNS and fq >= OBSERVE_MIN_TURNS:
            after_q_avg = obs['after_q_chars'] / aq
            free_avg    = obs['free_chars'] / fq
            if free_avg > after_q_avg * 1.5:
                verdict = '喜欢自己讲，少问多听'
            elif after_q_avg > free_avg * 1.5:
                verdict = '喜欢被问着聊，可以多起话头'
            else:
                verdict = '都行'
            mark_filled(profile, 'interaction_preference', verdict,
                        source='observed', confidence='low')

        # ── 情绪底色 ──
        # 全程 neutral 说明没有明显底色，不该硬扣一顶帽子。
        if turns >= OBSERVE_MIN_TURNS_EMOTION:
            cats = {k: v for k, v in obs.get('categories', {}).items()
                    if k not in ('neutral', 'crisis')}
            if cats:
                top, count = max(cats.items(), key=lambda kv: kv[1])
                if count / turns >= 0.3:
                    zh = {'depression': '偏抑郁', 'anxiety': '偏焦虑',
                          'anger': '容易上火', 'loneliness': '常觉得孤单',
                          'grief': '心里存着哀伤', 'positive': '心态挺开朗'}.get(top, top)
                    mark_filled(profile, 'emotional_baseline', zh,
                                source='observed', confidence='low')
```

补 config 导入：`OBSERVE_MIN_TURNS, OBSERVE_MIN_TURNS_EMOTION`

- [ ] **Step 4: 每轮调用**

`backend/services/llm_service.py`，在「步骤 10.4」之后追加：

```python
        # ── 步骤 10.6：行为观测（同步、纯计数，不调 LLM）─────────────────────
        if self.profile is not None and not crisis:
            try:
                # ai_asked_question 用的是**上一轮**回复是否以问句结尾——
                # 老人这一句正是对那一句的回应
                self.profile.observe_behavior(
                    elder_id, user_text, category,
                    ai_asked_question=meta['consecutive_questions'] > 0,
                )
            except Exception as e:
                logger.warning(f"行为观测失败（忽略）: {e}")
```

> 注意顺序：这一步必须在 `_note_reply_shape()` 之前读 `consecutive_questions`，或者显式记下本轮开始时的值。实现时把本轮开始的 `consecutive_questions` 先存到局部变量，避免读到已被本轮回复更新过的值。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_profile_observe.py selftest/test_elicitation_wiring.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/profile_service.py backend/services/llm_service.py backend/selftest/test_profile_observe.py
git commit -m "feat(profile): 观察类字段统计

性格、情绪底色只观察不问——问一个老人「您性格怎么样」本来就是荒谬的。
情绪底色所需的数据现有系统每轮都在产出（router 的 category），只是从没统计过。

样本不足时宁可留空：错误的性格判断会一直影响后续所有对话的语气。"
```

---

## Task 10: 主动开口护栏（纯逻辑）

**Files:**
- Create: `backend/services/proactive.py`
- Test: `backend/selftest/test_proactive.py`

**Interfaces:**
- Consumes: `config.PROACTIVE_QUIET_START / PROACTIVE_QUIET_END / PROACTIVE_MAX_PER_DAY / PROACTIVE_NO_ANSWER_GIVEUP`
- Produces:
  - `in_quiet_hours(now: datetime) -> bool`
  - `ProactiveGuard()`
  - `.can_speak(elder_id: str, *, crisis_vigilant: bool, now: datetime | None = None) -> tuple[bool, str]`
  - `.note_spoke(elder_id: str, now=None) -> None`
  - `.note_answered(elder_id: str) -> None`
  - `.note_no_answer(elder_id: str) -> None`

这三条护栏都不是功能需求，而是"别让这东西变成扰民设备"。抽成独立模块的理由：`LLMService.__init__` 会创建两个 API 客户端，护栏测试不该被迫连带 mock 它们。

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_proactive.py`：

```python
"""主动开口护栏。这些不是功能需求，是"别让这东西变成扰民设备"。"""
from datetime import datetime, timedelta, timezone

import pytest

from services.proactive import ProactiveGuard, in_quiet_hours

BJ = timezone(timedelta(hours=8))


def _t(h, m=0, day=13):
    return datetime(2026, 8, day, h, m, tzinfo=BJ)


@pytest.mark.parametrize('hour,quiet', [
    (20, False), (21, True), (23, True), (0, True),
    (6, True), (7, False), (10, False),
])
def test_quiet_hours_boundaries(hour, quiet):
    """21:00 起静默，07:00 解除。含起点不含终点。"""
    assert in_quiet_hours(_t(hour)) is quiet


def test_quiet_minute_boundaries():
    assert in_quiet_hours(_t(20, 59)) is False
    assert in_quiet_hours(_t(21, 0)) is True
    assert in_quiet_hours(_t(6, 59)) is True
    assert in_quiet_hours(_t(7, 0)) is False


def test_can_speak_in_daytime():
    g = ProactiveGuard()
    ok, why = g.can_speak('e1', crisis_vigilant=False, now=_t(10))
    assert ok, why


def test_blocked_in_quiet_hours():
    """作息字段抽错一个数字就可能变成半夜三点自己说话——这是硬边界。"""
    g = ProactiveGuard()
    ok, why = g.can_speak('e1', crisis_vigilant=False, now=_t(3))
    assert not ok
    assert 'quiet' in why


def test_blocked_during_crisis_vigilance():
    """刚经历过危机对话，设备过一会儿自己出声是惊吓，不是陪伴。"""
    g = ProactiveGuard()
    ok, why = g.can_speak('e1', crisis_vigilant=True, now=_t(10))
    assert not ok
    assert 'crisis' in why


def test_daily_quota():
    g = ProactiveGuard()
    for _ in range(3):
        assert g.can_speak('e1', crisis_vigilant=False, now=_t(10))[0]
        g.note_spoke('e1', now=_t(10))
        g.note_answered('e1')
    ok, why = g.can_speak('e1', crisis_vigilant=False, now=_t(10))
    assert not ok
    assert 'daily' in why


def test_quota_resets_next_day():
    g = ProactiveGuard()
    for _ in range(3):
        g.note_spoke('e1', now=_t(10, day=13))
        g.note_answered('e1')
    assert not g.can_speak('e1', crisis_vigilant=False, now=_t(10, day=13))[0]
    assert g.can_speak('e1', crisis_vigilant=False, now=_t(10, day=14))[0]


def test_gives_up_after_consecutive_no_answers():
    """连吃两次闭门羹就停手；否则设备变成定时扰民的喇叭，扰的是隔壁床的人。"""
    g = ProactiveGuard()
    g.note_spoke('e1', now=_t(9)); g.note_no_answer('e1')
    assert g.can_speak('e1', crisis_vigilant=False, now=_t(10))[0]
    g.note_spoke('e1', now=_t(10)); g.note_no_answer('e1')
    ok, why = g.can_speak('e1', crisis_vigilant=False, now=_t(11))
    assert not ok
    assert 'no_answer' in why


def test_answer_resets_no_answer_streak():
    g = ProactiveGuard()
    g.note_spoke('e1', now=_t(9)); g.note_no_answer('e1')
    g.note_spoke('e1', now=_t(10)); g.note_answered('e1')
    assert g.can_speak('e1', crisis_vigilant=False, now=_t(11))[0]


def test_elders_are_isolated():
    g = ProactiveGuard()
    for _ in range(3):
        g.note_spoke('e1', now=_t(10)); g.note_answered('e1')
    assert not g.can_speak('e1', crisis_vigilant=False, now=_t(10))[0]
    assert g.can_speak('e2', crisis_vigilant=False, now=_t(10))[0]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_proactive.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.proactive'`

- [ ] **Step 3: 实现**

创建 `backend/services/proactive.py`：

```python
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

    def note_answered(self, elder_id: str) -> None:
        """老人应答了，连续无应答清零。"""
        st = self._state.get(elder_id)
        if st:
            st['no_answer_streak'] = 0

    def note_no_answer(self, elder_id: str) -> None:
        st = self._state.get(elder_id)
        if st:
            st['no_answer_streak'] += 1
            if st['no_answer_streak'] >= PROACTIVE_NO_ANSWER_GIVEUP:
                logger.info(f"连续 {st['no_answer_streak']} 次无人应答，今天不再主动开口 | elder={elder_id}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_proactive.py -q`
Expected: PASS，17 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/proactive.py backend/selftest/test_proactive.py
git commit -m "feat(proactive): 主动开口护栏

夜间静默是不受作息字段影响的硬边界——采集来的数据不能直接驱动会发出
声音的行为，抽错一个数字就可能变成半夜三点自己说话。

连续无应答即当天停手：否则设备变成定时扰民的喇叭，扰的是隔壁床的人。"
```

---

## Task 11: 主动开口 prompt + `stream_proactive`

**Files:**
- Modify: `backend/prompts/templates.py`（新增 `PROACTIVE_SYSTEM_PROMPT` + `build_proactive_prompt`）
- Modify: `backend/services/llm_service.py`（新增 `stream_proactive`）
- Test: `backend/selftest/test_proactive_stream.py`

**Interfaces:**
- Consumes: Task 4 的 `ProfileService.get_address / get_context`；Task 5 的 `plan_elicitation`
- Produces:
  - `templates.build_proactive_prompt(address: str, trigger: str, memory_context: str = '', profile_context: str = '', elicitation_block: str = '') -> str`
  - `LLMService.stream_proactive(session_id: str, elder_id: str, trigger: str) -> AsyncGenerator[dict, None]`（事件结构与 `stream_reply` / `stream_closing` 一致：`meta → delta... → done`）

**这是本设计里风险最低的部分**：`stream_closing` 已经是「没有老人输入、后端自己生成一段话、走同样 SSE 结构」的完整链路，且已实机验证过。照它的形状写即可。

**两条硬规则必须在 prompt 里落实：**
1. **第一句不能是问句**（陈述打招呼在前，问题在后）
2. **称呼未知时用「您」，绝不编造**

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_proactive_stream.py`：

```python
"""主动开口的 prompt 与流式输出。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from prompts.templates import build_proactive_prompt


def test_prompt_forbids_leading_question():
    """设计文档 §6.2：第一句不能是问句，上来就问就是查户口。"""
    p = build_proactive_prompt('张阿姨', 'scheduled')
    assert '第一句' in p
    assert '不要用问句开头' in p


def test_prompt_uses_address():
    p = build_proactive_prompt('王老师', 'scheduled')
    assert '王老师' in p


def test_prompt_with_default_address_says_do_not_invent():
    """称呼未知时兜底「您」，且明确禁止编一个（设计文档 §3.5）。"""
    p = build_proactive_prompt('您', 'scheduled')
    assert '您' in p
    assert '不要自己编' in p


def test_silence_trigger_differs_from_scheduled():
    """沉默唤起是在对话中间，不该再打一次招呼。"""
    a = build_proactive_prompt('张阿姨', 'silence')
    b = build_proactive_prompt('张阿姨', 'scheduled')
    assert a != b
    assert '刚才安静了一会儿' in a


def test_prompt_embeds_elicitation_block():
    p = build_proactive_prompt('张阿姨', 'scheduled', elicitation_block='顺便聊聊老家')
    assert '顺便聊聊老家' in p


@pytest.fixture
def svc(tmp_path):
    from services.llm_service import LLMService
    from services.profile_service import ProfileService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch('services.profile_service.AsyncOpenAI'):
            with patch.object(LLMService, '_write_event', return_value={}):
                yield LLMService(profile_service=ProfileService(storage_dir=str(tmp_path)))


def _stream(chunks):
    async def gen():
        for c in chunks:
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=c))])
    m = AsyncMock()
    m.__aiter__ = lambda self: gen()
    return m


@pytest.mark.asyncio
async def test_stream_proactive_emits_meta_then_done(svc):
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _stream(['外头天不错啊。'])
        events = [e async for e in svc.stream_proactive('s1', 'e1', 'scheduled')]

    assert events[0]['type'] == 'meta'
    assert events[0]['category'] == 'proactive'
    assert events[0]['tts_params']['speed'] == 1.00
    assert events[-1]['type'] == 'done'
    assert events[-1]['full_text'] == '外头天不错啊。'


@pytest.mark.asyncio
async def test_proactive_reply_enters_history(svc):
    """主动说的话必须进历史，否则老人回应时模型不知道自己刚说了什么。"""
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _stream(['外头天不错啊。'])
        async for _ in svc.stream_proactive('s1', 'e1', 'scheduled'):
            pass
    assert svc.sessions['s1'][-1] == {'role': 'assistant', 'content': '外头天不错啊。'}


@pytest.mark.asyncio
async def test_proactive_failure_is_silent_no_fallback_text(svc):
    """设计文档 §9：主动开口失败静默放弃，不重试、不兜底说一句。

    和 closing 相反——closing 失败必须有兜底（不能把人晾在那儿），
    proactive 失败必须没有兜底（不能因为失败就反复出声）。
    """
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.side_effect = RuntimeError('api down')
        events = [e async for e in svc.stream_proactive('s1', 'e1', 'scheduled')]

    assert not any(e['type'] == 'delta' for e in events)
    assert events[-1]['type'] == 'done'
    assert events[-1]['full_text'] == ''


@pytest.mark.asyncio
async def test_proactive_marks_address_asked(svc):
    """称呼还没采到时，主动招呼顺带问，并记进画像。"""
    with patch.object(svc.client.chat.completions, 'create',
                      new_callable=AsyncMock) as api:
        api.return_value = _stream(['外头天不错。我该怎么称呼您呀？'])
        async for _ in svc.stream_proactive('s1', 'e1', 'scheduled'):
            pass
    assert svc.profile.get_profile('e1')['slots']['address']['ask_count'] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_proactive_stream.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_proactive_prompt'`

- [ ] **Step 3: 写 prompt**

在 `backend/prompts/templates.py` 的收束仪式那一节之后追加：

```python
# ─── 主动开口 ────────────────────────────────────────────────────────────────
# 老人不主动开口，App 就是一块沉默的屏幕。但主动开口最容易翻车的地方是
# "像查户口"——所以第一句必须是陈述，不能是问句。这恰好是 closing 的镜像：
# 收尾不提问，开场不逼问。

_PROACTIVE_TRIGGER_NOTE = {
    'scheduled': (
        '现在是你主动来跟他打个招呼。他可能刚起床、刚吃完饭，也可能正忙着别的。'
        '就像邻居顺路探个头，说一句就行，别铺开。'
    ),
    'silence': (
        '你们正聊着，刚才安静了一会儿。他可能在想事，也可能不知道说什么了。'
        '轻轻起个头把话接上，别问他"怎么不说话了"——那会让人尴尬。'
    ),
}


PROACTIVE_SYSTEM_PROMPT = """\
你是「蘅小年」，一个陪老年人聊天的伙伴。现在轮到你先开口。

## 这一次的情形
{trigger_note}

## 怎么称呼他
{address}
如果上面写的是「您」，说明还不知道他姓什么、怎么称呼——那就直接用「您」，
**不要自己编**一个称呼，也不要留空。叫错称呼比不叫名字伤人得多。

## 你已经知道的事（都是他以前自己说过的）
{memory_block}

## 你了解的他这个人
{profile_block}

## 这一轮顺带留意的
{elicitation_block}

## 硬规则（违反了这一整段就白说了）
1. **第一句必须是陈述句，不要用问句开头。** 先打招呼、先说点什么，
   有问题放到后面轻轻带出来。上来就问就是查户口。
2. 整段话**两三句就够**，说完就停。你是来陪他的，不是来汇报的。
3. 只能提上面记着的事，**绝不能编他没说过的**。什么都没记着，就说点眼前的
   （天气、时候），别硬凑细节。
4. 不要问"你还记得吗"，不要说"要保重""想开点"这类客套话。

## 说话风格
- 像老朋友顺口搭句话，句子短，说着顺口
- 别像念稿子，别用书面语\
"""


def build_proactive_prompt(
    address: str,
    trigger: str,
    memory_context: str = "",
    profile_context: str = "",
    elicitation_block: str = "",
) -> str:
    """构建主动开口的 System Prompt。

    Args:
        address: 称呼。拿不准时调用方应传 profile_service 的兜底值「您」。
        trigger: 'scheduled'（定时招呼）或 'silence'（沉默唤起）。
    """
    return PROACTIVE_SYSTEM_PROMPT.format(
        trigger_note      = _PROACTIVE_TRIGGER_NOTE.get(
            trigger, _PROACTIVE_TRIGGER_NOTE['scheduled']),
        address           = address or '您',
        memory_block      = memory_context or "（还没记下什么。别假装记得。）",
        profile_block     = profile_context or "（还不太了解他的情况。）",
        elicitation_block = elicitation_block or "（没什么特别要打听的，随便聊聊就好。）",
    )
```

- [ ] **Step 4: 写 `stream_proactive`**

`backend/services/llm_service.py`，在 `stream_closing` 之后追加：

```python
    # ─── 主动开口 ───────────────────────────────────────────────────────────

    async def stream_proactive(
        self,
        session_id: str = 'default',
        elder_id:   str = 'default_elder',
        trigger:    str = 'scheduled',
    ) -> AsyncGenerator[dict, None]:
        """AI 主动说一段话（定时招呼 / 沉默唤起）。

        形状和 stream_closing 完全一致（meta → delta... → done），前端复用
        同一条播放通路。

        与 closing 的一个关键差别：**生成失败时不兜底说一句**。closing 失败
        必须有兜底（不能把刚敞开心扉的人晾在那儿），proactive 失败必须没有
        兜底——不能因为失败就反复出声（设计文档 §9）。
        """
        address  = self.profile.get_address(elder_id) if self.profile else '您'
        memory   = self.memory.get_context(elder_id) if self.memory else ''
        prof_ctx = self.profile.get_context(elder_id) if self.profile else ''

        # 主动开口的时刻没有正在进行的叙事，是采集的最佳窗口（设计文档 §6.2）
        meta = self._get_session_meta(session_id)
        elicit_block, plan = '', None
        if self.profile is not None:
            try:
                plan = plan_elicitation(
                    self.profile.get_profile(elder_id),
                    slot_hint                  = '',
                    category                   = 'neutral',
                    phase                      = 'opening',
                    crisis                     = False,
                    crisis_vigilant            = self._is_crisis_vigilant(session_id),
                    restrain_questions         = False,
                    turns_since_last_elicit    = meta['turn_count'] - meta['last_elicit_turn'],
                    elicited_this_session      = meta['elicited_count'],
                    address_asked_this_session = meta['address_asked'],
                )
                if plan.mode != MODE_NONE:
                    elicit_block = build_elicitation_block(plan.mode, plan.slot, plan.is_stale)
            except Exception as e:
                logger.warning(f"主动开口采集规划失败（忽略）: {e}")
                plan = None

        system_prompt = build_proactive_prompt(
            address, trigger,
            memory_context    = memory,
            profile_context   = prof_ctx,
            elicitation_block = elicit_block,
        )

        # 主动开口一律用平缓语气，不跟着任何类别走
        tts_params = CATEGORY_TTS_PARAMS_MAP['neutral']
        yield {
            'type': 'meta', 'crisis': False, 'category': 'proactive',
            'strategy_id': '', 'strategy_name': '主动问候', 'tts_params': tts_params,
        }

        try:
            stream = await self.client.chat.completions.create(
                model       = QWEN_MODEL,
                messages    = [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user',   'content': '（现在轮到你先开口。）'},
                ],
                stream      = True,
                max_tokens  = LLM_MAX_TOKENS,
                temperature = LLM_TEMPERATURE,
                top_p       = LLM_TOP_P,
            )
        except Exception as e:
            # 静默放弃：不重试、不兜底说一句
            logger.warning(f"主动开口生成失败，本次放弃 (Session: {session_id}): {e}")
            yield {'type': 'done', 'full_text': '', 'crisis': False,
                   'category': 'proactive', 'strategy_id': '',
                   'strategy_name': '主动问候', 'tts_params': tts_params}
            return

        full_reply = ''
        async for chunk in stream:
            delta_text = chunk.choices[0].delta.content or ''
            if delta_text:
                full_reply += delta_text
                yield {'type': 'delta', 'text': delta_text, 'crisis': False}

        # 主动说的话必须进历史，否则老人回应时模型不知道自己刚说了什么
        if full_reply:
            self.sessions.setdefault(session_id, []).append(
                {'role': 'assistant', 'content': full_reply}
            )
            self._note_reply_shape(session_id, full_reply)
            if plan is not None and plan.mode != MODE_NONE and self.profile is not None:
                try:
                    self.profile.note_asked(elder_id, plan.slot)
                    if plan.slot == 'address':
                        meta['address_asked'] = True
                    else:
                        meta['elicited_count'] += 1
                        meta['last_elicit_turn'] = meta['turn_count']
                except Exception as e:
                    logger.warning(f"主动开口采集计数推进失败（忽略）: {e}")

        yield {
            'type': 'done', 'full_text': full_reply, 'crisis': False,
            'category': 'proactive', 'strategy_id': '',
            'strategy_name': '主动问候', 'tts_params': tts_params,
        }
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_proactive_stream.py -q`
Expected: PASS，10 passed

- [ ] **Step 6: Commit**

```bash
git add backend/prompts/templates.py backend/services/llm_service.py backend/selftest/test_proactive_stream.py
git commit -m "feat(proactive): 主动开口 prompt 与 stream_proactive

照 stream_closing 的形状写——那条链路已实机验证过，是本设计里风险最低的部分。

第一句必须是陈述不能是问句（上来就问就是查户口），称呼未知时用「您」绝不编造。
生成失败静默放弃、不兜底说一句：和 closing 恰好相反，closing 失败必须有兜底，
proactive 失败必须没有——不能因为失败就反复出声。"
```

---

## Task 12: `POST /llm/proactive` 端点 + 护栏接线

**Files:**
- Modify: `backend/routers/sse_llm.py`
- Modify: `backend/services/llm_service.py`（持有 `ProactiveGuard`，暴露 `can_speak_proactively` / `note_proactive_*`）
- Test: `backend/selftest/test_proactive_endpoint.py`

**Interfaces:**
- Consumes: Task 10 的 `ProactiveGuard`；Task 11 的 `stream_proactive`
- Produces:
  - `LLMService.can_speak_proactively(session_id: str, elder_id: str) -> tuple[bool, str]`
  - `LLMService.note_proactive_answered(elder_id: str) -> None`
  - `LLMService.note_proactive_no_answer(elder_id: str) -> None`
  - `POST /llm/proactive`（query: `session_id`、`elder_id`、`trigger`）→ SSE
  - `POST /llm/proactive/outcome`（query: `elder_id`、`answered: bool`）→ `{'status': 'ok'}`

**护栏必须在服务端而不是前端**：前端可以被绕过、可以有 bug、可以在多标签页里各跑一份计时器。夜间静默这种"不能出错"的规则必须由服务端拒绝。

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_proactive_endpoint.py`：

```python
"""端点层：护栏在服务端生效，前端只是触发器。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))


@pytest.fixture
def svc(tmp_path):
    from services.llm_service import LLMService
    from services.profile_service import ProfileService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch('services.profile_service.AsyncOpenAI'):
            with patch.object(LLMService, '_write_event', return_value={}):
                yield LLMService(profile_service=ProfileService(storage_dir=str(tmp_path)))


def test_guard_blocks_during_crisis_vigilance(svc):
    svc._enter_crisis_vigilance('s1')
    ok, why = svc.can_speak_proactively('s1', 'e1')
    assert not ok
    assert why == 'crisis_vigilant'


def test_guard_allows_normally(svc):
    with patch('services.proactive.in_quiet_hours', return_value=False):
        ok, _ = svc.can_speak_proactively('s1', 'e1')
    assert ok


def test_no_answer_streak_blocks(svc):
    with patch('services.proactive.in_quiet_hours', return_value=False):
        svc.note_proactive_no_answer('e1')
        svc.note_proactive_no_answer('e1')
        ok, why = svc.can_speak_proactively('s1', 'e1')
    assert not ok
    assert why == 'no_answer_giveup'


def test_answered_resets_streak(svc):
    with patch('services.proactive.in_quiet_hours', return_value=False):
        svc.note_proactive_no_answer('e1')
        svc.note_proactive_answered('e1')
        svc.note_proactive_no_answer('e1')
        ok, _ = svc.can_speak_proactively('s1', 'e1')
    assert ok


@pytest.mark.asyncio
async def test_endpoint_returns_blocked_event_when_guard_refuses(svc):
    """被护栏挡住时返回一个 blocked 事件，前端据此安静收场。"""
    import routers.sse_llm as mod
    mod.llm_service = svc
    svc._enter_crisis_vigilance('s1')

    resp = await mod.stream_proactive_endpoint(session_id='s1', elder_id='e1',
                                               trigger='scheduled')
    body = b''.join([chunk async for chunk in resp.body_iterator])
    payload = json.loads(body.decode().removeprefix('data: ').strip())
    assert payload['type'] == 'blocked'
    assert payload['reason'] == 'crisis_vigilant'


@pytest.mark.asyncio
async def test_endpoint_streams_when_allowed(svc):
    import routers.sse_llm as mod
    mod.llm_service = svc

    async def gen():
        yield MagicMock(choices=[MagicMock(delta=MagicMock(content='天不错啊。'))])
    stream = AsyncMock()
    stream.__aiter__ = lambda self: gen()

    with patch('services.proactive.in_quiet_hours', return_value=False):
        with patch.object(svc.client.chat.completions, 'create',
                          new_callable=AsyncMock) as api:
            api.return_value = stream
            resp = await mod.stream_proactive_endpoint(
                session_id='s1', elder_id='e1', trigger='scheduled')
            body = b''.join([c async for c in resp.body_iterator]).decode()

    assert '"type": "meta"' in body
    assert '天不错啊。' in body


@pytest.mark.asyncio
async def test_outcome_endpoint_records(svc):
    import routers.sse_llm as mod
    mod.llm_service = svc
    await mod.proactive_outcome(elder_id='e1', answered=False)
    await mod.proactive_outcome(elder_id='e1', answered=False)
    with patch('services.proactive.in_quiet_hours', return_value=False):
        ok, why = svc.can_speak_proactively('s1', 'e1')
    assert not ok and why == 'no_answer_giveup'
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_proactive_endpoint.py -q`
Expected: FAIL — `AttributeError: 'LLMService' object has no attribute 'can_speak_proactively'`

- [ ] **Step 3: LLMService 持有护栏**

`backend/services/llm_service.py`：

导入：

```python
from services.proactive import ProactiveGuard
```

`__init__` 里：

```python
        # 主动开口护栏（夜间静默 / 每日上限 / 无人应答）。放在服务端而不是前端：
        # 前端可以被绕过、可以有 bug、可以在多个标签页里各跑一份计时器。
        self.proactive_guard = ProactiveGuard()
```

追加三个方法（放在 `stream_proactive` 之后）：

```python
    def can_speak_proactively(self, session_id: str, elder_id: str) -> tuple[bool, str]:
        """这一刻能不能主动开口。返回 (可以吗, 不可以的原因)。"""
        return self.proactive_guard.can_speak(
            elder_id, crisis_vigilant=self._is_crisis_vigilant(session_id),
        )

    def note_proactive_answered(self, elder_id: str) -> None:
        self.proactive_guard.note_answered(elder_id)

    def note_proactive_no_answer(self, elder_id: str) -> None:
        self.proactive_guard.note_no_answer(elder_id)
```

- [ ] **Step 4: 加端点**

`backend/routers/sse_llm.py`，在 `/llm/closing` 之后追加：

```python
@router.post('/llm/proactive')
async def stream_proactive_endpoint(
    session_id: str = 'default',
    elder_id:   str = 'default_elder',
    trigger:    str = 'scheduled',
):
    """AI 主动开口（trigger: scheduled 定时招呼 / silence 沉默唤起）。

    护栏在**服务端**判断，不信任前端：夜间静默、每日上限、连续无应答、
    危机警戒期。被挡住时返回一条 blocked 事件，前端据此安静收场——
    不要重试，也不要提示老人。

    事件结构与 /llm/stream 一致（meta → delta... → done），前端复用同一条
    播放通路。
    """
    if llm_service is None:
        return {"error": "LLMService not initialized"}

    allowed, reason = llm_service.can_speak_proactively(session_id, elder_id)

    async def generate():
        if not allowed:
            logger.info(f"主动开口被护栏拦下 | session={session_id} | reason={reason}")
            payload = {'type': 'blocked', 'reason': reason}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return
        llm_service.proactive_guard.note_spoke(elder_id)
        try:
            async for chunk in llm_service.stream_proactive(session_id, elder_id, trigger):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"Proactive stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@router.post('/llm/proactive/outcome')
async def proactive_outcome(elder_id: str = 'default_elder', answered: bool = False):
    """主动招呼之后老人到底有没有搭话。

    前端在等待窗口结束时上报。连续无应答达到阈值后，当天不再主动开口——
    没有这条，设备会变成定时扰民的喇叭。
    """
    if llm_service is None:
        return {'status': 'error', 'message': 'LLMService not initialized'}
    if answered:
        llm_service.note_proactive_answered(elder_id)
    else:
        llm_service.note_proactive_no_answer(elder_id)
    return {'status': 'ok'}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_proactive_endpoint.py selftest/test_proactive_stream.py selftest/test_proactive.py -q`
Expected: PASS

- [ ] **Step 6: 全量离线回归**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest selftest/ -q \
  --ignore=selftest/test_asr.py --ignore=selftest/test_emotion.py \
  --ignore=selftest/test_model.py --ignore=selftest/test_ws.py \
  --ignore=selftest/test_tts.py
```

Expected: 只剩已知失效的 `test_refactor.py::test_config_loading` 一个 FAIL，其余全 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/routers/sse_llm.py backend/services/llm_service.py backend/selftest/test_proactive_endpoint.py
git commit -m "feat(proactive): /llm/proactive 端点，护栏在服务端

护栏不放前端：前端可以被绕过、可以有 bug、可以在多标签页里各跑一份计时器。
夜间静默这种不能出错的规则必须由服务端拒绝。

被挡住时返回 blocked 事件，前端安静收场——不重试，也不提示老人。"
```

---

## Task 13: 听力状况反向调 TTS（画像的唯一闭环）

**Files:**
- Modify: `backend/services/llm_service.py`（`_get_tts_params_by_category`）
- Test: `backend/selftest/test_hearing_tts.py`

**Interfaces:**
- Consumes: Task 4 的 `ProfileService.get_profile`
- Produces: `LLMService._get_tts_params_by_category(category: str, crisis: bool, elder_id: str = '') -> dict`（新增可选参数）

**偏离 spec §7.2 的一处（有意）**：spec 把这条写在 `tts_service.py`。实现放在 `_get_tts_params_by_category` 更对——TTS 参数是**后端算好、经 SSE 的 `meta`/`done` 事件发给前端**，由前端 WebAudio 实际播放的（`useTTS` 接收 `TTSParams`，`constants/TTS.ts` 不再维护副本）。改 `tts_service.py` 只影响服务端合成路径，前端拿到的参数不变，闭环就是断的。

这是画像里唯一能**反向改变系统行为**的字段：其他字段只让 AI 会说话，这个字段让 App 变得能用。

- [ ] **Step 1: 写失败的测试**

创建 `backend/selftest/test_hearing_tts.py`：

```python
"""听力状况 → TTS 语速。画像里唯一的闭环。"""
import pytest
from unittest.mock import MagicMock, patch

from services.profile_service import mark_filled


@pytest.fixture
def svc(tmp_path):
    from services.llm_service import LLMService
    from services.profile_service import ProfileService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        with patch('services.profile_service.AsyncOpenAI'):
            yield LLMService(profile_service=ProfileService(storage_dir=str(tmp_path)))


def test_unknown_hearing_uses_baseline(svc):
    p = svc._get_tts_params_by_category('neutral', False, elder_id='e1')
    assert p['speed'] == 1.00


def test_hard_of_hearing_slows_down(svc):
    prof = svc.profile.get_profile('e1')
    mark_filled(prof, 'sensory_hearing', '耳背，得大声说')
    p = svc._get_tts_params_by_category('neutral', False, elder_id='e1')
    assert p['speed'] < 1.00


def test_normal_hearing_does_not_slow_down(svc):
    prof = svc.profile.get_profile('e1')
    mark_filled(prof, 'sensory_hearing', '听得挺清楚')
    p = svc._get_tts_params_by_category('neutral', False, elder_id='e1')
    assert p['speed'] == 1.00


def test_adjustment_stacks_on_category_params(svc):
    """不是覆盖类别参数，是在它基础上再放慢。"""
    prof = svc.profile.get_profile('e1')
    mark_filled(prof, 'sensory_hearing', '耳背')
    grief = svc._get_tts_params_by_category('grief', False, elder_id='e1')
    assert grief['speed'] < 0.82
    assert grief['style'] == 'gentle', '风格仍由类别决定'


def test_speed_never_goes_below_floor(svc):
    """再慢也得像正常说话，不能慢到诡异。"""
    prof = svc.profile.get_profile('e1')
    mark_filled(prof, 'sensory_hearing', '耳背得厉害')
    p = svc._get_tts_params_by_category('depression', False, elder_id='e1')
    assert p['speed'] >= 0.70


def test_no_elder_id_returns_baseline(svc):
    p = svc._get_tts_params_by_category('neutral', False)
    assert p['speed'] == 1.00


def test_no_profile_service_is_safe():
    from services.llm_service import LLMService
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        svc = LLMService(profile_service=None)
        assert svc._get_tts_params_by_category('neutral', False, elder_id='e1')['speed'] == 1.00
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_hearing_tts.py -q`
Expected: FAIL — `test_hard_of_hearing_slows_down` 断言失败（speed 仍是 1.00）

- [ ] **Step 3: 实现**

`backend/services/llm_service.py`，在类里加常量与改方法：

```python
# 耳背时在类别语速基础上再放慢的比例，以及绝对下限。
# 下限存在的理由：再慢也得像正常说话——慢过头会变得诡异，反而更难听懂。
_HEARING_SLOWDOWN = 0.85
_MIN_SPEECH_SPEED = 0.70

# 判定"耳背"的关键词。画像里存的是老人自己的说法，不是枚举值，
# 所以这里用包含匹配而不是等值比较。
_HARD_OF_HEARING_HINTS = ('耳背', '听不清', '大声', '聋', '听力不好', '耳朵背')
```

```python
    def _get_tts_params_by_category(
        self, category: str, crisis: bool, elder_id: str = '',
    ) -> dict:
        """按心理类别取 TTS 参数，并按听力状况做一次放慢。

        这是画像里唯一能反向改变系统行为的字段（设计文档 §3.4）：其他字段
        只让 AI 会说话，这个字段让 App 变得能用。
        """
        key = 'crisis' if crisis else (category or 'neutral')
        params = dict(CATEGORY_TTS_PARAMS_MAP.get(
            key, CATEGORY_TTS_PARAMS_MAP['neutral']))

        if not elder_id or self.profile is None:
            return params
        try:
            slot = self.profile.get_profile(elder_id)['slots']['sensory_hearing']
            if slot['status'] in ('filled', 'stale') and any(
                hint in slot['value'] for hint in _HARD_OF_HEARING_HINTS
            ):
                params['speed'] = max(
                    _MIN_SPEECH_SPEED, round(params['speed'] * _HEARING_SLOWDOWN, 2))
        except Exception as e:
            logger.warning(f"听力参数调整失败（用默认语速）: {e}")
        return params
```

把 `stream_reply` 里两处 `self._get_tts_params_by_category(category, crisis)` 调用补上 `elder_id`：

```python
            'tts_params':    self._get_tts_params_by_category(category, crisis, elder_id),
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest selftest/test_hearing_tts.py selftest/test_llm_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/llm_service.py backend/selftest/test_hearing_tts.py
git commit -m "feat(profile): 听力状况反向调 TTS 语速

画像里唯一能反向改变系统行为的字段——其他字段只让 AI 会说话，
这个字段让 App 变得能用。

放在 _get_tts_params_by_category 而不是 tts_service：参数是后端算好经 SSE
发给前端、由前端 WebAudio 实际播放的，改 tts_service 前端拿到的参数不变，
闭环是断的。"
```

---

## Task 14: 前端 `fetchProactive`

**Files:**
- Modify: `mobile/hooks/useLLM.ts`

**Interfaces:**
- Consumes: Task 12 的 `POST /llm/proactive`、`POST /llm/proactive/outcome`
- Produces:
  - `runStream(...)` 返回值从 `void` 改为 `Promise<{ blocked: boolean; reason: string; fullText: string }>`（**新增返回值，老调用方忽略即可，向后兼容**）
  - `fetchProactive(sessionId: string, trigger: 'scheduled' | 'silence')`
  - `reportProactiveOutcome(answered: boolean)`

两处必须和普通回复不同的地方：

1. **`blocked` 事件要能传回调用方**。护栏在服务端，前端拿到 `blocked` 后要安静收场——不重试、不提示老人。
2. **失败时不能弹兜底文案**。`runStream` 现在错误时会 `setResponse(fallbackText)` 说一句"我刚才走神了"；主动开口失败时说这句是荒谬的（老人根本没说话）。

- [ ] **Step 1: 让 `runStream` 返回结果并支持"无兜底"**

`mobile/hooks/useLLM.ts`：

在 `runStream` 内部、`let pending = '';` 附近加两个局部变量：

```typescript
    let blocked = false;
    let blockReason = '';
```

在 SSE 事件分支里，`data.type === 'error'` 之前加：

```typescript
              } else if (data.type === 'blocked') {
                // 服务端护栏拒绝了这次主动开口（夜间静默/每日上限/连续无应答/
                // 危机警戒）。安静收场——不重试，也不要提示老人。
                blocked = true;
                blockReason = data.reason || 'unknown';
                console.log('[useLLM] 主动开口被护栏拦下:', blockReason);
```

`try` 块末尾（`onDone?.(capturedStrategyName);` 之前）改成：

```typescript
      if (blocked) {
        setIsStreaming(false);
        return { blocked: true, reason: blockReason, fullText: '' };
      }
```

`catch` 块里把无条件兜底改成"传了才兜底"：

```typescript
      console.error('LLM Fetch Error:', err);
      // fallbackText 为空串表示"这条链路失败时不许说话"（主动开口就是这样：
      // 老人根本没开口，冒出一句"我刚才走神了"是荒谬的）
      if (fallbackText) {
        setResponse(fallbackText);
        onDelta?.(fallbackText);
      }
      onDone?.();
      return { blocked: false, reason: 'error', fullText: '' };
```

并在 `try` 正常结束处返回：

```typescript
      onDone?.(capturedStrategyName);
      return { blocked: false, reason: '', fullText };
```

- [ ] **Step 2: 加 `fetchProactive` 与 `reportProactiveOutcome`**

在 `fetchClosing` 之后追加：

```typescript
  /**
   * AI 主动开口。trigger:
   *   'scheduled' —— 到点了主动招呼（当前无进行中的会话）
   *   'silence'   —— 对话中老人静默了一会儿，AI 先接上话
   *
   * 护栏在服务端。返回 blocked=true 时安静收场，**不要重试、不要提示老人**。
   * 生成失败时也不说兜底文案——老人根本没开口，冒出一句「我刚才走神了」
   * 是荒谬的（所以 fallbackText 传空串）。
   */
  const fetchProactive = useCallback(
    (sessionId: string, trigger: 'scheduled' | 'silence') =>
      runStream(
        `${baseUrl}/llm/proactive?session_id=${encodeURIComponent(sessionId)}` +
          `&elder_id=${encodeURIComponent(elderIdRef.current)}` +
          `&trigger=${trigger}`,
        { method: 'POST' },
        '',
      ),
    [baseUrl, runStream],
  );

  /**
   * 主动招呼之后老人到底有没有搭话。连续无应答达到阈值后，服务端当天不再
   * 主动开口——没有这条，设备会变成定时扰民的喇叭。
   */
  const reportProactiveOutcome = useCallback(async (answered: boolean) => {
    try {
      await fetch(
        `${baseUrl}/llm/proactive/outcome?elder_id=${encodeURIComponent(elderIdRef.current)}` +
          `&answered=${answered}`,
        { method: 'POST' },
      );
    } catch (err) {
      console.warn('[useLLM] 上报主动开口结果失败:', err);
    }
  }, [baseUrl]);
```

并把它们加进 hook 的返回值：

```typescript
  return {
    response, fetchReply, fetchClosing, fetchProactive, reportProactiveOutcome,
    abort, isStreaming, reset, strategyName, isCrisis,
  };
```

- [ ] **Step 3: 类型检查**

Run: `cd mobile && npx tsc --noEmit -p .`
Expected: 无输出（通过）

- [ ] **Step 4: Commit**

```bash
git add mobile/hooks/useLLM.ts
git commit -m "feat(proactive): 前端 fetchProactive

blocked 事件传回调用方，安静收场不重试不提示。
失败时不弹兜底文案——老人根本没开口，冒一句「我刚才走神了」是荒谬的。"
```

---

## Task 15: 沉默唤起

**Files:**
- Modify: `mobile/app/(tabs)/index.tsx`
- Modify: `mobile/constants/Session.ts`（新增 `SILENCE_PROMPT_MS`）

**Interfaces:**
- Consumes: Task 14 的 `fetchProactive`
- Produces: `Session.SILENCE_PROMPT_MS: number`（25000）

计时器有两个**必须排除**的区间，否则 AI 会在自己刚说完的瞬间又开口：
- TTS 播放期间（`ttsPlayingRef.current`）
- LLM 生成期间（`replyInFlightRef.current`）

- [ ] **Step 1: 加常量**

`mobile/constants/Session.ts` 末尾：

```typescript
/**
 * 老人静默多久之后 AI 先开口（毫秒）。
 *
 * 远长于 ASR 的 1.5 秒断句阈值——那个判断的是"这句话说完了没有"，
 * 这个判断的是"他是不是不想说了"。量级估计，需要实机调；调错方向时
 * 宁可往长了调：对老人而言，被打断的代价远大于多等一会儿。
 *
 * 后端 config.SILENCE_PROMPT_SEC 是同一个值，两边都要改。
 */
export const SILENCE_PROMPT_MS = 25000;
```

- [ ] **Step 2: 加计时器**

`mobile/app/(tabs)/index.tsx`：

导入补 `SILENCE_PROMPT_MS`，并在 refs 区加：

```typescript
  // 沉默唤起计时器。老人开着对话但一直没说话时，AI 先开口。
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
```

从 `useLLM` 解构里取出新方法：

```typescript
  const {
    fetchReply, fetchClosing, fetchProactive, reportProactiveOutcome,
    abort: abortLLM, reset: resetLLM, isCrisis,
  } = useLLM({ /* ...既有回调不变... */ });
```

在 `doEndSession` 之后追加：

```typescript
  /** 清掉沉默计时器。任何"有动静"的地方都要调它。 */
  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  /**
   * 重新开始计时。
   *
   * 必须排除两个区间，否则 AI 会在自己刚说完的瞬间又开口：
   *   1. TTS 播放期间（ttsPlayingRef）
   *   2. LLM 生成期间（replyInFlightRef）
   * 这两个区间结束时会各自再调一次本函数，所以这里直接不排是安全的。
   */
  const armSilenceTimer = useCallback(() => {
    clearSilenceTimer();
    if (!isRecording || isEndingRef.current) return;
    if (ttsPlayingRef.current || replyInFlightRef.current) return;

    silenceTimerRef.current = setTimeout(async () => {
      // 触发的一刻再查一次：这段时间里可能已经开始播/开始生成了
      if (!isRecording || isEndingRef.current) return;
      if (ttsPlayingRef.current || replyInFlightRef.current) return;

      replyInFlightRef.current = true;
      const result = await fetchProactive(sessionIdRef.current, 'silence');
      replyInFlightRef.current = false;

      // 被护栏拦下或生成失败：安静收场，不重试、不提示老人。
      // 但要重新计时——过一会儿条件可能就满足了。
      if (result?.blocked) armSilenceTimer();
    }, SILENCE_PROMPT_MS);
  }, [isRecording, fetchProactive, clearSilenceTimer, ttsPlayingRef]);
```

在 `onDone` 回调末尾（`replyInFlightRef.current = false;` 之后）加：

```typescript
      armSilenceTimer();
```

在 TTS 的 `onPlaybackDone` 那条链路上——即 `finishEndSession` 之外的普通播完场景——也要重新计时。最稳妥的做法是在 `onPlaybackDoneRef` 的赋值 effect 里包一层：

```typescript
  useEffect(() => {
    onPlaybackDoneRef.current = () => {
      finishEndSession();
      // 普通一轮播完（不在结束流程里）：重新开始等他说话
      if (!isEndingRef.current) armSilenceTimer();
    };
  }, [finishEndSession, armSilenceTimer]);
```

在 ASR 收到任何转写（老人开口了）的地方调 `clearSilenceTimer()`；本项目里最合适的挂点是 `onDelta`/用户消息落地处，实现时找到"老人这一句被确认"的那一个回调，在其开头加：

```typescript
      clearSilenceTimer();
```

在 `toggleConversation` 的**开始分支**末尾（`start(sessionId);` 之后）加 `armSilenceTimer();`，**结束分支**开头加 `clearSilenceTimer();`。

在 `doEndSession` 开头加 `clearSilenceTimer();`。

并加一个卸载清理：

```typescript
  useEffect(() => clearSilenceTimer, [clearSilenceTimer]);
```

- [ ] **Step 3: 类型检查**

Run: `cd mobile && npx tsc --noEmit -p .`
Expected: 无输出

- [ ] **Step 4: 实机验证**

启动后端与前端，开始对话，说一句话，然后**保持安静 25 秒**。

Expected：AI 主动说一句话（陈述句开头，不是问句）。期间不要在 AI 说话时计时——观察它不会连着说两段。

```bash
cd backend && ./.venv/Scripts/python.exe -m uvicorn main:app --port 8050
```

- [ ] **Step 5: Commit**

```bash
git add mobile/constants/Session.ts "mobile/app/(tabs)/index.tsx"
git commit -m "feat(proactive): 会话内沉默唤起

计时器排除 TTS 播放期与 LLM 生成期，否则 AI 会在自己刚说完的瞬间又开口。
被护栏拦下时安静收场并重新计时——过一会儿条件可能就满足了。"
```

---

## Task 16: 定时招呼 + 无人应答收场

**Files:**
- Modify: `mobile/app/(tabs)/index.tsx`
- Modify: `mobile/constants/Session.ts`（新增默认时间表与等待窗口）

**Interfaces:**
- Consumes: Task 14 的 `fetchProactive` / `reportProactiveOutcome`
- Produces: `Session.PROACTIVE_SCHEDULE: number[]`、`Session.PROACTIVE_NO_ANSWER_MS: number`

**前提：设备常驻前台**（床头平板/挂墙屏）。这是 spec §11 的未决问题之一，本任务只做前台常驻形态；App 在后台/设备休眠时**不补发**——否则回前台会一次性说三段话。

- [ ] **Step 1: 加常量**

`mobile/constants/Session.ts` 末尾：

```typescript
/**
 * 默认主动招呼的时间点（小时，本地时间）。
 *
 * 画像采到 daily_routine 之前用这张表。注意服务端还有一道夜间静默硬边界
 * （21:00-07:00），这张表改错了也不会半夜出声。
 */
export const PROACTIVE_SCHEDULE = [9, 14, 19];

/** 主动招呼说完后，开麦等多久算没人应答（毫秒）。后端同名参数是 20 秒。 */
export const PROACTIVE_NO_ANSWER_MS = 20000;
```

- [ ] **Step 2: 加定时器**

`mobile/app/(tabs)/index.tsx` refs 区：

```typescript
  // 今天已经触发过的时间点（小时）。防止同一个整点内反复触发。
  const firedHoursRef = useRef<Set<string>>(new Set());
  const noAnswerTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 主动招呼之后，老人有没有搭话
  const proactiveAnsweredRef = useRef(false);
```

追加定时招呼逻辑：

```typescript
  /**
   * 定时主动招呼。
   *
   * 每分钟查一次表，到点且当前没有进行中的对话就自动开一个会话、AI 先说话、
   * 然后自动开麦。
   *
   * 错过不补发（设计文档 §9）：App 在后台或设备休眠时错过的时间点直接跳过，
   * 否则回前台会一次性说三段话。firedHoursRef 用「日期+小时」做键，天然满足
   * 这一点——过了那个小时就再也不会触发。
   */
  useEffect(() => {
    const tick = async () => {
      if (isRecording || isEndingRef.current) return;

      const now = new Date();
      const key = `${now.toDateString()}#${now.getHours()}`;
      if (!PROACTIVE_SCHEDULE.includes(now.getHours())) return;
      if (firedHoursRef.current.has(key)) return;
      firedHoursRef.current.add(key);

      const sessionId = newSessionId();
      sessionIdRef.current = sessionId;
      setMessages([]);
      setCurrentEmotion('neutral');
      setErrorMessage('');
      proactiveAnsweredRef.current = false;

      const result = await fetchProactive(sessionId, 'scheduled');
      // 被护栏拦下（夜间静默/每日上限/连续无应答）：安静收场，什么都不做
      if (result?.blocked || !result?.fullText) return;

      // 说完了自动开麦，等他搭话
      start(sessionId);
      armNoAnswerTimer();
    };

    const id = setInterval(tick, 60_000);
    tick();
    return () => clearInterval(id);
  }, [isRecording, fetchProactive, start]);

  /**
   * 无人应答收场。
   *
   * 定时招呼时老人很可能不在。等一个窗口没人搭话就安静停掉、上报服务端；
   * 连续几次之后服务端当天不再主动开口——没有这条，设备会变成定时扰民的
   * 喇叭，而且扰的是隔壁床的人。
   */
  const armNoAnswerTimer = useCallback(() => {
    if (noAnswerTimerRef.current) clearTimeout(noAnswerTimerRef.current);
    noAnswerTimerRef.current = setTimeout(() => {
      noAnswerTimerRef.current = null;
      if (proactiveAnsweredRef.current) return;
      // 没人应答：停掉录音，安静收场，不再呼叫
      stopASR();
      clearSilenceTimer();
      setMessages([]);
      reportProactiveOutcome(false);
    }, PROACTIVE_NO_ANSWER_MS);
  }, [stopASR, clearSilenceTimer, reportProactiveOutcome]);
```

在"老人这一句被确认"的那个回调里（Task 15 里加 `clearSilenceTimer()` 的同一处）加：

```typescript
      // 他搭话了：撤掉无人应答的收场计时
      if (noAnswerTimerRef.current) {
        clearTimeout(noAnswerTimerRef.current);
        noAnswerTimerRef.current = null;
      }
      if (!proactiveAnsweredRef.current) {
        proactiveAnsweredRef.current = true;
        reportProactiveOutcome(true);
      }
```

卸载清理：

```typescript
  useEffect(() => () => {
    if (noAnswerTimerRef.current) clearTimeout(noAnswerTimerRef.current);
  }, []);
```

- [ ] **Step 3: 类型检查**

Run: `cd mobile && npx tsc --noEmit -p .`
Expected: 无输出

- [ ] **Step 4: 实机验证（把时间表临时改成当前小时）**

把 `PROACTIVE_SCHEDULE` 临时改成 `[new Date().getHours()]`，刷新页面。

Expected：
1. AI 自己开口说一句（陈述句开头），然后自动进入录音状态
2. **不搭话**：20 秒后安静停下，界面回到初始态，不再重复呼叫
3. 再刷新两次重复第 2 步 → 第三次应当**完全不出声**（服务端连续无应答护栏生效）
4. 后端日志出现 `主动开口被护栏拦下 | reason=no_answer_giveup`

验证完把 `PROACTIVE_SCHEDULE` 改回 `[9, 14, 19]`。

- [ ] **Step 5: 夜间静默实机验证**

把后端 `config.PROACTIVE_QUIET_START` 临时改成当前小时，重启后端，触发一次定时招呼。

Expected：**完全不出声**，后端日志 `reason=quiet_hours`。验证完改回 `21`。

- [ ] **Step 6: Commit**

```bash
git add mobile/constants/Session.ts "mobile/app/(tabs)/index.tsx"
git commit -m "feat(proactive): 定时主动招呼与无人应答收场

错过不补发：firedHoursRef 用「日期+小时」做键，App 在后台错过的时间点
直接跳过——否则回前台会一次性说三段话。

无人应答就安静收场并上报，连续几次后服务端当天不再出声。"
```

---

## 自查（写完计划后的检查结果）

**1. Spec 覆盖**

| Spec 章节 | 落在哪个 Task |
|---|---|
| §3.1 画像与台账分开 | Task 4（独立文件/独立锁） |
| §3.2 三类字段 | Task 1 |
| §3.3 已故亲人派生视图 | **未覆盖，见下方遗留** |
| §3.4 采集优先级 | Task 1（`askable_by_priority`） |
| §3.5 address 特殊路径 | Task 3 + Task 5 + Task 11 |
| §3.6 birth_year 存年份 | Task 3 |
| §4.1 slot_hint 并进路由 | Task 6 |
| §4.2 两套门槛 | Task 5 |
| §4.3 采集强度 + address 豁免 | Task 5 |
| §4.4 不抢策略决策权 | Task 7（prompt 措辞 + 冲突时策略优先） |
| §5.2-5.4 状态机 / 沉默即拒绝 | Task 2 |
| §5.5 stale 用确认话术 | Task 3（渲染）+ Task 7（话术） |
| §5.6 观察类无 asked | Task 9 |
| §6.1 /llm/proactive | Task 12 |
| §6.2 话头三来源 + 称呼兜底 | Task 11 |
| §6.3 沉默唤起 | Task 15 |
| §6.4 定时招呼 + 三条护栏 | Task 10 + Task 16 |
| §6.5 前端改动 | Task 15 + Task 16 |
| §7.1-7.3 模块边界与存储 | Task 1/4/5/10（多拆了 2 个纯逻辑模块，理由见"文件结构"） |
| §7.4 elder_id 一人一设备 | **已实现**（`mobile/constants/Session.ts`），无需任务 |
| §8.1-8.2 数据流 | Task 7 / Task 12 |
| §8.3 独立抽取调用 | Task 8 |
| §8.4 配置参数 | Task 1 |
| §9 错误处理 | 分散在各 Task，每处都有对应测试 |
| §10 测试策略 | 各 Task 的测试步骤 |

**2. 一处有意的偏离**

Spec §7.2 把"听力状况调 TTS"放在 `tts_service.py`。Task 13 改放在 `LLMService._get_tts_params_by_category`，理由写在该任务里：TTS 参数是后端算好经 SSE 发给前端、由前端 WebAudio 实际播放的，改 `tts_service.py` 前端拿到的参数不变，闭环是断的。

**3. 一处遗留（spec §3.3 已故亲人派生视图）**

台账 `people[].status` 已有"已故"信息，spec 要求画像层做一个**读时派生**的视图供哀伤类别参考。本计划没有为它单列任务：它需要 `ProfileService` 反向读 `MemoryService`，会在两个刻意解耦的服务之间建立依赖。

**建议**：作为独立的小任务在本计划完成后处理，由 `llm_service`（已经同时持有两个服务）在构建 prompt 时合成，而不是让 `ProfileService` 去读台账。执行本计划时**不要**顺手实现它。

**4. 类型一致性检查**

- `_route_category` 四元组：Task 6 定义，Task 7 消费，13 处 mock 同步迁移 ✓
- `plan_elicitation` 关键字参数：Task 5 定义，Task 7 与 Task 11 两处调用参数名一致 ✓
- `ElicitPlan.mode/slot/is_stale`：Task 5 定义，Task 7/11 消费 ✓
- `build_normal_prompt` 新增 `profile_context` / `elicitation_block`：Task 7 定义并在同一任务里消费 ✓
- `_get_tts_params_by_category(category, crisis, elder_id='')`：Task 13 加参数，同任务内更新两处调用点 ✓
- `runStream` 返回值：Task 14 新增，Task 15/16 消费 `result.blocked` / `result.fullText` ✓
- `ProfileService.get_profile/get_context/get_address/note_asked/observe_turn/observe_behavior`：Task 4/8/9 定义，Task 7/11/13 消费 ✓

## 执行前的提醒

- **Task 6 是唯一会打破现有测试的任务**，它必须在一个 commit 里同时改产品代码和 13 处 mock，中间状态是红的。
- **Task 5 是本计划的核心**，26 个测试穷举了两套门槛。它若做错，后面所有任务都建立在错误的采集判定上——这个任务的 review 要格外仔细。
- **Task 15/16 的实机验证不能跳过**。"顺水推舟在敏感叙事下是否违和"和"定时招呼像不像查户口"是自动化测试测不出来的（spec §10 明确写了这一点）。
