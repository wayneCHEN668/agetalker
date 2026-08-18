"""云端 ASR 故障分类与降级行为。

背景：账户欠费时 DashScope 会异步回调 on_error(Arrearage)。旧实现不区分故障
类型，一律「下一帧音频到达时重建」，于是退化成每帧重建一次的死循环——日志刷屏、
持续锤打云端 API，而老人那头永远停在「稍等一下」。这些测试锁住修复后的行为。
"""

import asyncio
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.asr_service import (  # noqa: E402
    _is_permanent_error,
    _RecognitionCallbackAdapter,
)


class _FakeResult:
    """仿 dashscope 的 RecognitionResult：只要 code / message 两个字段。"""

    def __init__(self, code, message):
        self.code = code
        self.message = message


# ── 故障分类 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code, message", [
    # 实测触发本次 bug 的那条：http_code 44
    ("Arrearage", "Access denied, please make sure your account is in good standing."),
    ("InvalidApiKey", "The API key is invalid."),
    ("Unauthorized", "Unauthorized"),
    ("Throttling.Quota", "Free allocated quota exceeded."),
    ("ModelNotExist", "Model not exist."),
    ("InvalidParameter", "Required parameter missing."),
])
def test_permanent_errors_are_classified_permanent(code, message):
    """重试也无用的故障必须判为永久，否则会退化成无限重建循环。"""
    assert _is_permanent_error(code, message) is True


@pytest.mark.parametrize("code, message", [
    (None, "Speech recognition has stopped."),
    ("RequestTimeout", "Request timed out."),
    ("InternalError", "Internal server error."),
    ("ServiceUnavailable", "Service temporarily unavailable, please try again."),
    (None, ""),
])
def test_transient_errors_are_not_classified_permanent(code, message):
    """会话超时/网络抖动必须留在重建路径上——这些重建就能恢复。"""
    assert _is_permanent_error(code, message) is False


def test_classification_is_case_insensitive():
    """SDK 的措辞大小写不该影响判定。"""
    assert _is_permanent_error("ARREARAGE", "") is True
    assert _is_permanent_error("arrearage", "") is True


# ── 回调把「是否永久」传给路由层 ─────────────────────────────────────────────

def _capture_disconnect(result_or_close):
    """跑一次 on_error/on_close，返回传给断连回调的 permanent 值。

    回调经 run_coroutine_threadsafe 投递，所以需要一个真实运行的事件循环。
    """
    captured = {}

    async def scenario():
        loop = asyncio.get_running_loop()
        done = asyncio.Event()

        async def on_disconnect(permanent: bool):
            captured['permanent'] = permanent
            done.set()

        adapter = _RecognitionCallbackAdapter(
            session_id='test_session',
            async_callback=None,
            event_loop=loop,
            disconnect_callback=on_disconnect,
        )
        result_or_close(adapter)
        await asyncio.wait_for(done.wait(), timeout=2)

    asyncio.run(scenario())
    return captured['permanent']


def test_on_error_arrearage_signals_permanent():
    """欠费 → permanent=True，路由层据此降级而不是重建。"""
    result = _FakeResult(
        'Arrearage',
        'Access denied, please make sure your account is in good standing.',
    )
    assert _capture_disconnect(lambda a: a.on_error(result)) is True


def test_on_error_transient_signals_not_permanent():
    """超时 → permanent=False，保持原有的重建行为。"""
    result = _FakeResult('RequestTimeout', 'Request timed out.')
    assert _capture_disconnect(lambda a: a.on_error(result)) is False


def test_on_close_alone_signals_not_permanent():
    """裸 close 一律当瞬时：真永久故障会先走 on_error 那条路。"""
    assert _capture_disconnect(lambda a: a.on_close()) is False


def test_disconnect_fires_only_once_on_error_then_close():
    """SDK 在 on_error 之后必定紧跟 on_close，不能因此重建两次。"""
    calls = []

    async def scenario():
        loop = asyncio.get_running_loop()

        async def on_disconnect(permanent: bool):
            calls.append(permanent)

        adapter = _RecognitionCallbackAdapter(
            session_id='test_session',
            async_callback=None,
            event_loop=loop,
            disconnect_callback=on_disconnect,
        )
        adapter.on_error(_FakeResult('Arrearage', 'Access denied'))
        adapter.on_close()          # SDK 紧接着就会调这个
        await asyncio.sleep(0.1)    # 给投递到事件循环的回调留出执行时间

    asyncio.run(scenario())
    assert calls == [True], f"期望只触发一次且为永久，实际: {calls}"


def test_deactivate_suppresses_disconnect():
    """我们主动 end_session() 时不该触发重建。"""
    calls = []

    async def scenario():
        loop = asyncio.get_running_loop()

        async def on_disconnect(permanent: bool):
            calls.append(permanent)

        adapter = _RecognitionCallbackAdapter(
            session_id='test_session',
            async_callback=None,
            event_loop=loop,
            disconnect_callback=on_disconnect,
        )
        adapter.deactivate()
        adapter.on_close()
        await asyncio.sleep(0.1)

    asyncio.run(scenario())
    assert calls == [], f"正常关闭不该触发断连回调，实际: {calls}"
