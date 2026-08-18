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

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from config import (
    ELICIT_MAX_ASK_COUNT, PROFILE_DIR,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, ROUTER_EXTRA_BODY,
    OBSERVE_MIN_TURNS, OBSERVE_MIN_TURNS_EMOTION,
)
from services.profile_schema import (
    SLOTS, ASKABLE_SLOTS, OBSERVABLE_SLOTS,
    askable_by_priority, is_askable, is_valid_slot, slot_zh,
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


def render_emergency_contact(profile: dict) -> str:
    """危机轮能说出口的那个人。没录过就返回空串。

    没有 DEFAULT_ADDRESS 那样的兜底——称呼拿不准还能叫「您」，联系人拿不准
    没有任何东西可以顶上。空串在 prompt 那边会翻译成「反过来问他身边有谁」，
    这正是唯一安全的处理方式。

    这个字段是 EXTERNAL 类型，不在 render_profile() 渲染范围内（那里只渲染
    问出来的和观察出来的），所以危机路径要单独读一次。
    """
    slot = profile.get('slots', {}).get('emergency_contact')
    if slot and slot['status'] == STATUS_FILLED and slot['value'].strip():
        return slot['value'].strip()
    return ''


def _year_from_age_or_year(text: str, now: Optional[datetime] = None):
    """「我自己」那一页的岁数输入：四位年份和岁数都收，一律换算成年份。

    这一栏对老人显示的是「岁数」，他会输 83；但存进去的必须是出生年份
    （存年龄一年后就是错的，见 set_birth_year）。两个区间不重叠，没有歧义。
    都不像就原样返回，让 set_birth_year 去拒。
    """
    try:
        n = int(str(text).strip())
    except (TypeError, ValueError):
        return text
    this_year = (now or _now()).year
    if 1900 <= n <= this_year:
        return n                      # 已经是年份
    if 40 <= n <= 120:
        return this_year - n          # 是岁数
    return text


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

        # 抽取用轻量模型，与主生成模型完全分离
        self.client = AsyncOpenAI(
            api_key  = DEEPSEEK_API_KEY,
            base_url = DEEPSEEK_BASE_URL,
        )

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

    def get_emergency_contact(self, elder_id: str) -> str:
        """危机轮能说出口的那个人。没录过返回空串，调用方据此改成反问。"""
        return render_emergency_contact(self.get_profile(elder_id))

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

    # ─── 「我自己」那一页：老人自己看、自己改 ────────────────────────────
    # 只开放 askable。external（紧急联系人/药名/房间号）是护理员录的；
    # observable（话多话少/情绪底色）是从对话行为统计出来的，手改下一轮
    # 就被 observe_behavior 盖掉，给个能改的入口只会让人白改一次。

    def list_editable_slots(self, elder_id: str) -> list[dict]:
        """页面要显示的那一列，按优先级排。没采到的 value 是空串。"""
        profile = self.get_profile(elder_id)
        return [
            {
                'name':   name,
                'zh':     slot_zh(name),
                'value':  profile['slots'][name]['value'],
                'status': profile['slots'][name]['status'],
            }
            for name in askable_by_priority()
        ]

    def set_slot_manually(self, elder_id: str, slot_name: str, value: str) -> bool:
        """手工改一个字段。空值表示清掉。成功返回 True。

        清空是必须有的：实盘画像里 address 的值是「我」——从 AI 自己那句
        「我该怎么称呼你呀？」里抽错的。改不掉错值的编辑页没有意义。
        清空后回到 unknown，AI 以后会重新问。
        """
        if not is_askable(slot_name):
            return False

        profile = self.get_profile(elder_id)
        text = str(value).strip()

        if not text:
            slot = profile['slots'][slot_name]
            slot.update({
                'value': '', 'status': STATUS_UNKNOWN, 'last_filled': '',
                # evidence/source 一起清掉：留着旧依据，下一次抽取会拿它当
                # 上下文，等于没清干净
                'source': '', 'confidence': '', 'evidence': '',
            })
            self._save(elder_id, profile)
            return True

        if slot_name == 'birth_year':
            # 这一栏对老人显示的是「岁数」，他会输 83；schema 只存四位年份
            # （存年龄一年后就是错的，见 set_birth_year）。转换放在这儿，
            # schema 不动。
            ok = set_birth_year(profile, _year_from_age_or_year(text), source='manual')
            if not ok:
                return False
        else:
            mark_filled(profile, slot_name, text, source='manual', confidence='high')

        self._save(elder_id, profile)
        return True

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

    # ─── 抽取（后台异步）───────────────────────────────────────────────────

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
            if not isinstance(data, dict):
                raise ValueError(f'画像文件顶层不是对象: {type(data).__name__}')

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
        except Exception as e:
            logger.error(f"画像读取失败，按空画像处理 ({path}): {e}")
            return empty_profile(elder_id)

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
