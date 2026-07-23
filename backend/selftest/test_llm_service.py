import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_service import LLMService


@pytest.fixture
def llm_service():
    """初始化 LLMService，mock 掉 AsyncOpenAI 客户端。"""
    with patch('services.llm_service.AsyncOpenAI') as mock_cls:
        mock_cls.return_value = MagicMock()
        service = LLMService()
    return service


def test_crisis_detection(llm_service):
    """验证危机词检测逻辑。"""
    assert llm_service._check_crisis("我不想活了") is True
    assert llm_service._check_crisis("活着没意思") is True
    assert llm_service._check_crisis("没人需要我了") is True   # v2 新增
    assert llm_service._check_crisis("交代后事") is True       # v2 新增
    assert llm_service._check_crisis("今天天气不错") is False
    assert llm_service._check_crisis("我想吃苹果") is False


def test_tts_params_mapping(llm_service):
    """验证情绪到 TTS 参数的映射。"""
    # 危机模式：应使用 _crisis 参数
    assert llm_service._get_tts_params({}, True)['style'] == 'gentle'
    assert llm_service._get_tts_params({}, True)['speed'] == 0.82

    # 正常模式
    assert llm_service._get_tts_params({'label': 'happy'}, False)['style'] == 'cheerful'
    assert llm_service._get_tts_params({'label': 'sad'}, False)['pitch'] == -2
    assert llm_service._get_tts_params({'label': 'neutral'}, False)['style'] == 'neutral'


def test_multi_session_isolation(llm_service):
    """验证多会话历史隔离。"""
    llm_service.sessions['user1'] = [{'role': 'user', 'content': 'hello'}]
    llm_service.sessions['user2'] = [{'role': 'user', 'content': 'hi'}]

    assert len(llm_service.sessions['user1']) == 1
    llm_service.reset('user1')
    assert len(llm_service.sessions['user1']) == 0
    assert len(llm_service.sessions['user2']) == 1


@pytest.mark.asyncio
async def test_history_cropping(llm_service):
    """验证对话历史裁剪逻辑（async 适配）。"""
    from config import LLM_MAX_HISTORY_TURNS
    session_id = 'test_crop'
    llm_service.sessions[session_id] = []

    # 填充超出上限的历史（每轮 2 条消息）
    for i in range(LLM_MAX_HISTORY_TURNS + 5):
        llm_service.sessions[session_id].append({'role': 'user', 'content': f'msg {i}'})
        llm_service.sessions[session_id].append({'role': 'assistant', 'content': f'reply {i}'})

    current_len = len(llm_service.sessions[session_id])
    assert current_len > LLM_MAX_HISTORY_TURNS * 2

    # Mock 路由 LLM（避免真实 API 调用）
    with patch.object(llm_service, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', 'test routing', '')  # v5: 三元组 (category, matched_signals, strategy_id)
        # Mock 流式 API 调用
        with patch.object(llm_service.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            # 构造一个空的流式响应
            mock_create.return_value = AsyncMock()
            mock_create.return_value.__aiter__.return_value = []

            gen = llm_service.stream_reply("new msg", {"label": "neutral"}, session_id)
            chunks = []
            async for chunk in gen:
                chunks.append(chunk)

    # 历史记录应该被裁剪到上限
    assert len(llm_service.sessions[session_id]) <= LLM_MAX_HISTORY_TURNS * 2


@pytest.mark.asyncio
async def test_routing_fallback_on_error(llm_service):
    """验证路由 LLM 异常时降级为 neutral，不中断对话。"""
    # Mock 路由 LLM 底层调用抛出异常（走 _route_category 内部 try/except）
    # self.client 被路由和生成共用——第一次 create 是路由，第二次是生成
    with patch.object(llm_service.client.chat.completions, 'create', new_callable=AsyncMock) as mock_api:
        # 第一次调用（路由）→ 抛异常
        # 第二次调用（生成）→ 返回空流
        empty_stream = AsyncMock()
        empty_stream.__aiter__.return_value = []
        mock_api.side_effect = [
            RuntimeError("路由服务不可用"),
            empty_stream,
        ]

        gen = llm_service.stream_reply("测试消息", {"label": "neutral"}, "test_fallback")
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)

    # 不应产生 error 事件（路由失败降级为 neutral 后正常完成）
    errors = [c for c in chunks if c.get('type') == 'error']
    assert len(errors) == 0
    # 应该正常产生 done 事件
    done_events = [c for c in chunks if c.get('type') == 'done']
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_crisis_skips_routing(llm_service):
    """验证危机关键词命中时跳过路由 LLM 调用。"""
    with patch.object(llm_service, '_route_category', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = ('neutral', '')
        with patch.object(llm_service.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = AsyncMock()
            mock_create.return_value.__aiter__.return_value = []

            gen = llm_service.stream_reply("我不想活了", {"label": "neutral"}, "test_crisis")
            chunks = []
            async for chunk in gen:
                chunks.append(chunk)

    # 路由 LLM 不应被调用（危机关键词直接拦截）
    mock_route.assert_not_called()
    # 所有 chunk 应标记 crisis: true
    for chunk in chunks:
        assert chunk.get('crisis') is True
    # done 事件应使用 crisis TTS 参数 + category='crisis'
    done = next(c for c in chunks if c.get('type') == 'done')
    assert done['category'] == 'crisis'
    assert done['tts_params']['style'] == 'gentle'
    assert done['tts_params']['speed'] == 0.82


def test_category_tts_params(llm_service):
    """验证心理类别 → TTS 参数映射（语义驱动）。"""
    # 哀伤/抑郁 → 最缓
    assert llm_service._get_tts_params_by_category('grief', False)['speed'] == 0.82
    assert llm_service._get_tts_params_by_category('depression', False)['style'] == 'gentle'
    # 积极 → 明快
    assert llm_service._get_tts_params_by_category('positive', False)['speed'] == 1.05
    assert llm_service._get_tts_params_by_category('positive', False)['style'] == 'cheerful'
    # 中性 → 正常
    assert llm_service._get_tts_params_by_category('neutral', False)['speed'] == 1.00
    # 危机 → 最缓
    assert llm_service._get_tts_params_by_category('neutral', True)['speed'] == 0.82
    # 未知类别 → 降级 neutral
    assert llm_service._get_tts_params_by_category('unknown', False)['speed'] == 1.00
