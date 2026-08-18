"""
整句合并测试。

针对的问题：老人一句话中间停顿两三秒是常事，云端 VAD 会把它切成两三个 final，
系统于是拿着半句话（「我昨天去了」）就去回复了。

光调大 VAD 静音阈值解决不了——调大之后每一轮回复都跟着变慢。正确的分工是
云端 VAD 只管转写分段，「这一轮说完了没有」由 SentenceAggregator 判断。
"""

import sys
import os
import asyncio
import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.ws_asr import SentenceAggregator
from config import ASR_MERGE_WINDOW_MS


def _make():
    """返回 (aggregator, 已提交文本列表)。"""
    committed: list[str] = []

    async def commit(text: str):
        committed.append(text)

    return SentenceAggregator(commit), committed


async def _sleep_ms(ms: float):
    await asyncio.sleep(ms / 1000.0)


# ─── 合并行为 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sentence_ending_with_period_still_merges():
    """
    以句号结尾的一段，后面接着说 → 照样要合并。

    这是真实事故的回归测试：转写「上面写的名字。叫王翠芬。」——句号出现在
    一句连贯话的中间。第一版按尾部标点做自适应窗口（见到句号就只等 350ms），
    恰好在老人边想边说的停顿处判定他说完了，把话切断，还因此生成了两条回复。
    ASR 的标点是按韵律停顿插的，不是语义终止信号，不能用它来判断说完没有。
    """
    agg, committed = _make()

    agg.add_final('上面写的名字。')
    await _sleep_ms(500)          # 超过老版本那个 350ms 短窗口

    agg.note_partial()            # 老人接着说
    agg.add_final('叫王翠芬。')
    await _sleep_ms(ASR_MERGE_WINDOW_MS + 300)

    assert committed == ['上面写的名字。叫王翠芬。'], f"实际: {committed}"


@pytest.mark.asyncio
async def test_resumed_speech_merges_into_one_turn():
    """
    句中停顿被切成两个 final，老人接着说 → 合并成一句。

    「我昨天去了」+ 停顿 + 「趟医院。」应该作为一句完整的话交给下游，
    而不是让系统对着「我昨天去了」就开口回复。
    """
    agg, committed = _make()

    agg.add_final('我昨天去了，')
    await _sleep_ms(ASR_MERGE_WINDOW_MS * 0.4)   # 还没到提交时间

    agg.note_partial()                            # 老人又开口了
    agg.add_final('趟医院。')
    await _sleep_ms(ASR_MERGE_WINDOW_MS + 300)

    assert committed == ['我昨天去了，趟医院。'], f"实际: {committed}"


@pytest.mark.asyncio
async def test_single_complete_sentence_commits_on_its_own():
    """说完一句就没下文了 → 窗口到点正常提交。"""
    agg, committed = _make()
    agg.add_final('我今天挺好的。')
    await _sleep_ms(ASR_MERGE_WINDOW_MS + 300)
    assert committed == ['我今天挺好的。']


@pytest.mark.asyncio
async def test_partial_alone_does_not_commit():
    """只有中间结果、没有 final 时不该提交任何东西。"""
    agg, committed = _make()
    agg.note_partial()
    await _sleep_ms(ASR_MERGE_WINDOW_MS + 250)
    assert committed == []


@pytest.mark.asyncio
async def test_three_fragments_all_merge():
    """连着三段碎片也要并成一句——老人讲长句时很常见。"""
    agg, committed = _make()
    for part in ['我记得那年', '大概是八三年', '那会儿日子苦。']:
        agg.note_partial()
        agg.add_final(part)
        await _sleep_ms(80)
    await _sleep_ms(ASR_MERGE_WINDOW_MS + 300)
    assert committed == ['我记得那年大概是八三年那会儿日子苦。']


@pytest.mark.asyncio
async def test_cancel_drops_everything():
    """连接断了：丢弃缓冲，不留悬空任务。"""
    agg, committed = _make()
    agg.add_final('说到一半，')
    agg.cancel()
    await _sleep_ms(ASR_MERGE_WINDOW_MS + 250)
    assert committed == []
    assert agg.buffered == ''


@pytest.mark.asyncio
async def test_buffered_text_visible_while_accumulating():
    """攒的过程中要能拿到当前完整文本，供前端实时显示整句在长。"""
    agg, _ = _make()
    assert agg.add_final('我昨天去了，') == '我昨天去了，'
    agg.note_partial()
    assert agg.add_final('趟医院。') == '我昨天去了，趟医院。'
    agg.cancel()
