"""
长程记忆服务：事实台账（跨会话）+ 滚动摘要（会话内）。

为什么需要这个模块
------------------
对话历史只保留 LLM_MAX_HISTORY_TURNS=6 轮（约 3~5 分钟），而一次陪伴对话可能
持续一小时、120 轮以上。也就是说 95% 的内容对模型不可见。

这本身还不是最糟的。真正的问题是它和 templates.py 里的「事实红线」形成死锁：
红线禁止编造老人没说过的事，但历史滑出去之后，第 40 分钟的模型根本不知道
第 5 分钟提过的「老伴叫建国」。于是它只剩两条路——反问「建国是谁」（对老人
来说就是"你根本没在听"，陪伴场景里最伤人的失败），或者顺着语气编一段（正好
违反红线）。

两层记忆分别解决两件事：
- 事实台账（ledger）：保**事实精确性**。人物、事件、偏好，结构化存储，可以被
  精确回指。按 elder_id 跨会话持久化——明天还记得今天聊过建国。
- 滚动摘要（summary）：保**叙事连贯性**。这次聊天到目前为止的脉络，压缩成一段
  短文。按 session_id 维护，会话结束后精简留档。

关键设计决策
------------
1. **只从老人的原话里抽取事实，不从 AI 的回复里抽。**
   AI 回复是模型生成的，可能已经含有幻觉；如果把它当事实写进台账，等于把幻觉
   洗成"记忆"，之后每一轮都会被当作真事引用，错误会持续放大且再也无法追溯。
   这是本模块最重要的一条约束。

2. **抽取走后台异步，不占关键路径。**
   在 stream_reply 产出 done 之后再触发，当轮回复的延迟完全不受影响。代价是
   本轮说的事实从下一轮开始可用——对连贯性没有实质影响。

3. **合并而不是追加。**
   同一个人反复被提到时合并 notes，不新建条目。否则一小时后台账里会有十几个
   "建国"，注入 prompt 后模型反而更糊涂。
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    ROUTER_EXTRA_BODY,
    MEMORY_DIR,
    MEMORY_MAX_PEOPLE,
    MEMORY_MAX_EVENTS,
    MEMORY_MAX_PREFERENCES,
    MEMORY_MAX_NOTES_PER_PERSON,
    MEMORY_SUMMARY_MAX_CHARS,
    MEMORY_MAX_SESSION_SUMMARIES,
)

logger = logging.getLogger(__name__)

_BEIJING = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(_BEIJING).isoformat()


# ─── 抽取 prompt ─────────────────────────────────────────────────────────────

EXTRACT_SYSTEM_PROMPT = """\
你是老年人陪伴系统的「事实抽取」模块。你的任务是从老人刚说的这句话里，
抽取出值得长期记住的事实，输出 JSON。

## 最重要的规则
只抽取老人**自己说出来的**内容。绝对不要推测、不要补全、不要把常识当事实。
- 老人说「我老伴走了三年了」→ 可以记：老伴，已故，走了三年
- 老人说「我老伴走了三年了」→ 不能记：老伴的名字、怎么走的、老人很孤独
宁可少记，不能记错。记错了会在后面的对话里被当成真事反复引用，比没记更糟。

## 抽取什么
- people：老人提到的人（家人、老友、邻居、护工）。name 用老人的原话称呼
  （「老伴」「王老头」「小李」都行，没提名字就用称呼）。
- events：老人经历过或提到的具体事情。
- preferences：爱好、口味、习惯、明确表达的喜欢/不喜欢。

## 输出格式
只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释：

{
  "people": [{"name": "称呼", "relation": "关系，没说就留空", "status": "在世|已故|不确定", "note": "这句话里提到的关于这个人的一件事，没有就留空"}],
  "events": [{"summary": "≤20字，一件具体的事"}],
  "preferences": [{"content": "≤15字，一条偏好"}]
}

这句话里没有值得记的事实时，三个数组都留空。这是很常见的情况，不要硬凑。
"""


SUMMARY_SYSTEM_PROMPT = """\
你是老年人陪伴系统的「对话摘要」模块。下面给你的是**老人自己说过的话**（AI 的
回复已经剔除），把它压缩成一段简短的叙事摘要，供后续对话回顾用。

要求：
- 只概括他说过的内容和聊到的话题
- 不要添加任何原文里没有的信息，不要推测、不要补全
- 保留人名、称呼、具体的事件细节——这些正是后面可能要回指的东西
- 用第三人称陈述，{max_chars} 字以内
- 如果给了「已有摘要」，把新内容并进去重写成一段完整的，不要简单拼接

只输出摘要正文，不要任何前缀或解释。
"""


# ─── 台账操作（纯函数，不依赖 LLM，可独立测试）────────────────────────────────


def empty_ledger(elder_id: str) -> dict:
    return {
        'elder_id': elder_id,
        'people': [],
        'events': [],
        'preferences': [],
        'session_summaries': [],
    }


def _merge_person(people: list[dict], incoming: dict) -> None:
    """把一条新抽到的人物信息合并进台账（同名合并，不新建条目）。"""
    name = (incoming.get('name') or '').strip()
    if not name:
        return

    note = (incoming.get('note') or '').strip()
    relation = (incoming.get('relation') or '').strip()
    status = (incoming.get('status') or '').strip()

    for person in people:
        if person['name'] == name:
            # 关系/状态：之前空着才补，不覆盖已有的（先说的通常更可靠）
            if relation and not person.get('relation'):
                person['relation'] = relation
            if status and status != '不确定' and not person.get('status'):
                person['status'] = status
            if note and note not in person['notes']:
                person['notes'].append(note)
                person['notes'] = person['notes'][-MEMORY_MAX_NOTES_PER_PERSON:]
            person['last_mentioned'] = _now()
            return

    people.append({
        'name': name,
        'relation': relation,
        'status': status if status != '不确定' else '',
        'notes': [note] if note else [],
        'last_mentioned': _now(),
    })


def _merge_simple(items: list[dict], incoming: dict, key: str, cap: int) -> None:
    """合并 events / preferences 这类只有一个文本字段的条目，按文本去重。"""
    value = (incoming.get(key) or '').strip()
    if not value:
        return
    for item in items:
        if item[key] == value:
            item['last_mentioned'] = _now()
            return
    items.append({key: value, 'last_mentioned': _now()})
    if len(items) > cap:
        # 超出上限时淘汰最久没被提到的
        items.sort(key=lambda x: x.get('last_mentioned', ''))
        del items[: len(items) - cap]


def merge_facts(ledger: dict, facts: dict) -> dict:
    """把一次抽取结果合并进台账。就地修改并返回同一个 ledger。"""
    for person in facts.get('people') or []:
        if isinstance(person, dict):
            _merge_person(ledger['people'], person)

    if len(ledger['people']) > MEMORY_MAX_PEOPLE:
        ledger['people'].sort(key=lambda x: x.get('last_mentioned', ''))
        del ledger['people'][: len(ledger['people']) - MEMORY_MAX_PEOPLE]

    for event in facts.get('events') or []:
        if isinstance(event, dict):
            _merge_simple(ledger['events'], event, 'summary', MEMORY_MAX_EVENTS)

    for pref in facts.get('preferences') or []:
        if isinstance(pref, dict):
            _merge_simple(ledger['preferences'], pref, 'content', MEMORY_MAX_PREFERENCES)

    return ledger


def render_ledger(ledger: dict) -> str:
    """把台账渲染成注入 system prompt 的文本。空台账返回空串。"""
    if not ledger:
        return ''

    lines: list[str] = []

    people = ledger.get('people') or []
    if people:
        lines.append('【他提到过的人】')
        for p in people:
            bits = [p['name']]
            if p.get('relation'):
                bits.append(f"（{p['relation']}）")
            if p.get('status'):
                bits.append(f"[{p['status']}]")
            line = ''.join(bits)
            if p.get('notes'):
                line += '：' + '；'.join(p['notes'])
            lines.append(f'- {line}')

    events = ledger.get('events') or []
    if events:
        lines.append('【他说过的事】')
        lines.extend(f"- {e['summary']}" for e in events)

    prefs = ledger.get('preferences') or []
    if prefs:
        lines.append('【他的喜好习惯】')
        lines.extend(f"- {p['content']}" for p in prefs)

    past = ledger.get('session_summaries') or []
    if past:
        lines.append('【以前聊过的】')
        lines.extend(f"- {s['date'][:10]}：{s['text']}" for s in past)

    return '\n'.join(lines)


# ─── 服务 ────────────────────────────────────────────────────────────────────


class MemoryService:
    """
    长程记忆服务。

    用法（由 LLMService 调用）：
        memory.get_context(elder_id)              # 注入 prompt 的台账文本
        memory.get_summary(session_id)            # 注入 prompt 的本次对话摘要
        await memory.observe_turn(...)            # 后台调用，抽取并落盘
        await memory.fold_into_summary(...)       # 后台调用，压缩滑出的历史
        memory.close_session(elder_id, session_id)  # 会话结束，摘要留档
    """

    def __init__(self, storage_dir: str = MEMORY_DIR):
        self.storage_dir = Path(storage_dir)
        self._ledgers: dict[str, dict] = {}
        self._summaries: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # 抽取/摘要都用轻量模型，与主生成模型完全分离
        self.client = AsyncOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        logger.info(f"记忆服务初始化完成 ✅ (存储目录: {self.storage_dir})")

    # ─── 读取（同步，走内存，供 prompt 构建使用）──────────────────────────

    def get_ledger(self, elder_id: str) -> dict:
        """取台账，首次访问时从磁盘惰性加载。"""
        if elder_id not in self._ledgers:
            self._ledgers[elder_id] = self._load(elder_id)
        return self._ledgers[elder_id]

    def get_context(self, elder_id: str) -> str:
        """台账渲染成的 prompt 文本。"""
        return render_ledger(self.get_ledger(elder_id))

    def get_summary(self, session_id: str) -> str:
        """本次会话到目前为止的滚动摘要。"""
        return self._summaries.get(session_id, '')

    # ─── 写入（异步，后台调用）──────────────────────────────────────────

    async def observe_turn(self, elder_id: str, user_text: str) -> dict:
        """
        从老人这一句话里抽取事实、合并进台账并落盘。

        只传 user_text——不传 AI 的回复。AI 回复是生成出来的，可能含幻觉，
        把它当事实写进台账等于把幻觉洗成记忆，之后会被反复引用且无法追溯。
        """
        if not user_text.strip():
            return {}

        facts = await self._extract_facts(user_text)
        if not facts or not any(facts.get(k) for k in ('people', 'events', 'preferences')):
            return {}

        async with self._lock_for(elder_id):
            ledger = self.get_ledger(elder_id)
            merge_facts(ledger, facts)
            self._save(elder_id, ledger)

        logger.info(
            f"记忆更新 | elder={elder_id} | "
            f"人物 {len(facts.get('people') or [])} 事件 {len(facts.get('events') or [])} "
            f"偏好 {len(facts.get('preferences') or [])}"
        )
        return facts

    async def fold_into_summary(self, session_id: str, dropped_messages: list[dict]) -> str:
        """把滑出历史窗口的消息压缩进本会话的滚动摘要。"""
        if not dropped_messages:
            return self._summaries.get(session_id, '')

        text = self._summarize_input(dropped_messages)
        if not text.strip():
            return self._summaries.get(session_id, '')

        previous = self._summaries.get(session_id, '')
        summary = await self._summarize(text, previous)
        if summary:
            self._summaries[session_id] = summary[:MEMORY_SUMMARY_MAX_CHARS]
            logger.debug(f"滚动摘要已更新 | session={session_id} | {len(summary)} 字")
        return self._summaries.get(session_id, '')

    def close_session(self, elder_id: str, session_id: str) -> None:
        """会话结束：把本次摘要留档进台账，供以后跨会话回指。"""
        summary = self._summaries.pop(session_id, '')
        if not summary:
            return
        ledger = self.get_ledger(elder_id)
        ledger.setdefault('session_summaries', []).append({
            'session_id': session_id,
            'date': _now(),
            'text': summary,
        })
        ledger['session_summaries'] = ledger['session_summaries'][-MEMORY_MAX_SESSION_SUMMARIES:]
        self._save(elder_id, ledger)
        logger.info(f"会话摘要已留档 | elder={elder_id} | session={session_id}")

    def reset_session(self, session_id: str) -> None:
        """丢弃某个会话的滚动摘要（不影响跨会话台账）。"""
        self._summaries.pop(session_id, None)

    # ─── LLM 调用 ───────────────────────────────────────────────────────

    async def _extract_facts(self, user_text: str) -> dict:
        try:
            resp = await self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {'role': 'system', 'content': EXTRACT_SYSTEM_PROMPT},
                    {'role': 'user', 'content': f'老人说：「{user_text}」'},
                ],
                temperature=0.0,
                max_tokens=400,
                response_format={'type': 'json_object'},
                extra_body=ROUTER_EXTRA_BODY,
            )
            raw = resp.choices[0].message.content
            return json.loads(raw.strip()) if raw else {}
        except Exception as e:
            # 记忆是增强能力，抽取失败不该影响对话本身
            logger.warning(f"事实抽取失败（忽略，不影响对话）: {e}")
            return {}

    async def _summarize(self, conversation_text: str, previous: str) -> str:
        try:
            user_content = (
                (f'已有摘要：{previous}\n\n' if previous else '')
                + f'新的对话内容：\n{conversation_text}'
            )
            resp = await self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {'role': 'system',
                     'content': SUMMARY_SYSTEM_PROMPT.format(max_chars=MEMORY_SUMMARY_MAX_CHARS)},
                    {'role': 'user', 'content': user_content},
                ],
                temperature=0.2,
                max_tokens=500,
                extra_body=ROUTER_EXTRA_BODY,
            )
            return (resp.choices[0].message.content or '').strip()
        except Exception as e:
            logger.warning(f"滚动摘要生成失败（忽略，不影响对话）: {e}")
            return previous

    @staticmethod
    def _summarize_input(messages: list[dict]) -> str:
        """
        只把老人自己说的话交给摘要模型，AI 的回复不进来。

        原先两边都传，这留了一条幻觉洗白的通道：AI 某一轮编了句话，被摘要吸收
        成「聊过的事」，之后每轮都作为事实注入 prompt，错误一直滚下去。这跟
        台账只从老人原话抽取是同一条原则——之前只堵了台账那条，漏了这条。
        """
        return '\n'.join(
            f"老人：{m['content']}"
            for m in messages
            if m.get('role') == 'user' and m.get('content')
        )

    # ─── 持久化 ─────────────────────────────────────────────────────────

    def _lock_for(self, elder_id: str) -> asyncio.Lock:
        if elder_id not in self._locks:
            self._locks[elder_id] = asyncio.Lock()
        return self._locks[elder_id]

    def _path(self, elder_id: str) -> Path:
        # elder_id 来自客户端，做一次保守清洗防止路径穿越
        safe = ''.join(c for c in elder_id if c.isalnum() or c in '-_')[:64] or 'unknown'
        return self.storage_dir / f'{safe}.json'

    def _load(self, elder_id: str) -> dict:
        path = self._path(elder_id)
        if not path.exists():
            return empty_ledger(elder_id)
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            # 补齐可能缺失的字段，兼容早期写下的文件
            base = empty_ledger(elder_id)
            base.update({k: v for k, v in data.items() if k in base})
            return base
        except Exception as e:
            logger.error(f"台账读取失败，按空台账处理 ({path}): {e}")
            return empty_ledger(elder_id)

    def _save(self, elder_id: str, ledger: dict) -> None:
        path = self._path(elder_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再替换，避免写到一半被读到半个 JSON
            tmp = path.with_suffix('.json.tmp')
            tmp.write_text(
                json.dumps(ledger, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            tmp.replace(path)
        except Exception as e:
            logger.error(f"台账写入失败 ({path}): {e}")
