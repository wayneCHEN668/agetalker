import sys
import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.memory_service import (
    MemoryService,
    empty_ledger,
    merge_facts,
    render_ledger,
)


# ─── 台账合并（纯函数，不碰 LLM）──────────────────────────────────────────────


def test_same_person_merges_not_duplicates():
    """
    同一个人反复被提到时必须合并进同一条，而不是不断新建。

    这是长对话里最容易出问题的地方：一小时里「老伴」可能被提十几次，
    每次都新建一条的话，注入 prompt 后模型看到十几个老伴，反而更糊涂。
    """
    ledger = empty_ledger('e1')

    merge_facts(ledger, {'people': [
        {'name': '建国', 'relation': '老伴', 'status': '已故', 'note': '走了三年'},
    ]})
    merge_facts(ledger, {'people': [
        {'name': '建国', 'relation': '', 'status': '', 'note': '爱吃她包的饺子'},
    ]})

    assert len(ledger['people']) == 1
    person = ledger['people'][0]
    assert person['relation'] == '老伴'
    assert person['status'] == '已故'
    assert person['notes'] == ['走了三年', '爱吃她包的饺子']


def test_existing_relation_not_overwritten():
    """先说的关系更可靠，后面抽到的不覆盖已有的。"""
    ledger = empty_ledger('e1')
    merge_facts(ledger, {'people': [{'name': '小李', 'relation': '护工', 'note': ''}]})
    merge_facts(ledger, {'people': [{'name': '小李', 'relation': '邻居', 'note': ''}]})
    assert ledger['people'][0]['relation'] == '护工'


def test_duplicate_events_and_prefs_deduped():
    ledger = empty_ledger('e1')
    for _ in range(3):
        merge_facts(ledger, {
            'events': [{'summary': '隔壁王老头走了'}],
            'preferences': [{'content': '爱听京剧'}],
        })
    assert len(ledger['events']) == 1
    assert len(ledger['preferences']) == 1


def test_caps_are_enforced():
    """条目上限生效，防止一小时对话把台账和 prompt 撑爆。"""
    from config import MEMORY_MAX_EVENTS
    ledger = empty_ledger('e1')
    for i in range(MEMORY_MAX_EVENTS + 10):
        merge_facts(ledger, {'events': [{'summary': f'第{i}件事'}]})
    assert len(ledger['events']) == MEMORY_MAX_EVENTS


def test_empty_extraction_is_noop():
    """抽不到东西是常态（大量闲聊句子没有可记的事实），不该产生空条目。"""
    ledger = empty_ledger('e1')
    merge_facts(ledger, {'people': [], 'events': [], 'preferences': []})
    merge_facts(ledger, {})
    assert ledger['people'] == []
    assert ledger['events'] == []


def test_render_includes_names_and_notes():
    ledger = empty_ledger('e1')
    merge_facts(ledger, {
        'people': [{'name': '建国', 'relation': '老伴', 'status': '已故', 'note': '走了三年'}],
        'preferences': [{'content': '爱听京剧'}],
    })
    text = render_ledger(ledger)
    assert '建国' in text
    assert '老伴' in text
    assert '走了三年' in text
    assert '爱听京剧' in text


def test_render_empty_ledger_is_blank():
    assert render_ledger(empty_ledger('e1')) == ''


# ─── 持久化 ──────────────────────────────────────────────────────────────────


def test_save_and_reload_roundtrip(tmp_path):
    """跨会话持久化：写盘再读回来，事实还在。"""
    svc = MemoryService(storage_dir=str(tmp_path))
    ledger = svc.get_ledger('elder_a')
    merge_facts(ledger, {'people': [
        {'name': '建国', 'relation': '老伴', 'status': '已故', 'note': '走了三年'},
    ]})
    svc._save('elder_a', ledger)

    # 全新的服务实例（模拟重启），从磁盘读回
    reloaded = MemoryService(storage_dir=str(tmp_path))
    text = reloaded.get_context('elder_a')
    assert '建国' in text
    assert '走了三年' in text


def test_elder_id_path_traversal_is_sanitized(tmp_path):
    """elder_id 来自客户端，不能让它写到目录外面去。"""
    svc = MemoryService(storage_dir=str(tmp_path))
    path = svc._path('../../etc/passwd')
    assert tmp_path in path.parents
    assert '..' not in path.name


def test_corrupt_ledger_falls_back_to_empty(tmp_path):
    """台账文件损坏时按空台账处理，不能让对话起不来。"""
    svc = MemoryService(storage_dir=str(tmp_path))
    path = svc._path('elder_b')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{ this is not json', encoding='utf-8')
    ledger = svc.get_ledger('elder_b')
    assert ledger['people'] == []


# ─── 抽取与摘要（mock 掉 LLM）────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observe_turn_merges_and_persists(tmp_path):
    svc = MemoryService(storage_dir=str(tmp_path))
    fake = {
        'people': [{'name': '建国', 'relation': '老伴', 'status': '已故', 'note': '走了三年'}],
        'events': [], 'preferences': [],
    }
    with patch.object(svc, '_extract_facts', new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = fake
        await svc.observe_turn('elder_c', '我老伴建国走了三年了')

    assert '建国' in svc.get_context('elder_c')
    saved = json.loads(svc._path('elder_c').read_text(encoding='utf-8'))
    assert saved['people'][0]['name'] == '建国'


@pytest.mark.asyncio
async def test_extraction_failure_does_not_break(tmp_path):
    """抽取失败只是没记住，绝不能影响对话。"""
    svc = MemoryService(storage_dir=str(tmp_path))
    svc.client.chat.completions.create = AsyncMock(side_effect=RuntimeError('网络炸了'))
    result = await svc.observe_turn('elder_d', '我老伴走了')
    assert result == {}
    assert svc.get_context('elder_d') == ''


def test_summary_input_excludes_assistant_turns():
    """
    摘要只能拿老人自己说的话，AI 的回复必须剔除。

    否则 AI 某一轮编的话会被摘要吸收成「聊过的事」，之后每轮作为事实注入
    prompt，幻觉就这么洗白成了记忆，错误一直滚下去。
    """
    text = MemoryService._summarize_input([
        {'role': 'user', 'content': '我今天去了趟菜市场'},
        {'role': 'assistant', 'content': '你老伴以前也常陪你去吧？'},   # AI 编的
        {'role': 'user', 'content': '买了点萝卜'},
    ])
    assert '菜市场' in text
    assert '萝卜' in text
    assert '老伴' not in text, "AI 的回复混进摘要输入了"
    assert '心伴' not in text


def test_fact_red_line_examples_are_disclaimed():
    """
    事实红线里的举例必须带「这是另一段对话、不许搬用」的警告。

    真实对话里出过事故：示例里的「老王」「五十年邻居」被模型当成可用素材说了
    出来，而老人从没提过邻居。裸示例（尤其标着「好的回应」的）会被当成 few-shot
    模板照抄，这条断言防止它被改回去。
    """
    from prompts.templates import build_normal_prompt
    prompt = build_normal_prompt(
        'grief', {'label_zh': '悲伤', 'score': 0.8, 'trend': '首次对话',
                  'valence': 0.1, 'arousal': 0.2}, '哀伤信号', 'externalize',
    )
    assert '另外一段对话' in prompt, "举例没有标明属于别的对话"
    assert '毫无关系' in prompt
    assert '一个字都不许搬进你的回复' in prompt
    # 不能再出现「你早先说过……」这种凭空断言老人说过什么的句式模板
    assert '你早先说过你俩' not in prompt


@pytest.mark.asyncio
async def test_close_session_archives_summary(tmp_path):
    """会话结束时摘要留档，下次对话能回指。"""
    svc = MemoryService(storage_dir=str(tmp_path))
    svc._summaries['s1'] = '老人聊起了老伴建国，说他走了三年。'
    svc.close_session('elder_e', 's1')

    reloaded = MemoryService(storage_dir=str(tmp_path))
    text = reloaded.get_context('elder_e')
    assert '建国' in text
    assert 's1' not in svc._summaries   # 已从活跃摘要里移出
