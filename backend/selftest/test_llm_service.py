# e:\MyDoc\APP\agetalker\backend\selftest\test_llm_service.py

import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_service import LLMService

@pytest.fixture
def llm_service():
    with patch('services.llm_service.OpenAI'):
        service = LLMService()
        return service

def test_crisis_detection(llm_service):
    """验证危机词检测逻辑。"""
    assert llm_service._check_crisis("我不想活了") == True
    assert llm_service._check_crisis("活着没意思") == True
    assert llm_service._check_crisis("今天天气不错") == False
    assert llm_service._check_crisis("我想吃苹果") == False

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

def test_history_cropping(llm_service):
    """验证对话历史裁剪逻辑。"""
    from config import LLM_MAX_HISTORY_TURNS
    session_id = 'test_crop'
    llm_service.sessions[session_id] = []
    
    # 填充超出上限的历史（每轮 2 条消息）
    for i in range(LLM_MAX_HISTORY_TURNS + 5):
        llm_service.sessions[session_id].append({'role': 'user', 'content': f'msg {i}'})
        llm_service.sessions[session_id].append({'role': 'assistant', 'content': f'reply {i}'})
    
    current_len = len(llm_service.sessions[session_id])
    assert current_len > LLM_MAX_HISTORY_TURNS * 2
    
    # 模拟 API 调用触发裁剪
    with patch.object(llm_service.client.chat.completions, 'create') as mock_create:
        mock_create.return_value = [] # 模拟流式返回为空
        gen = llm_service.stream_reply("new msg", {"label": "neutral"}, session_id)
        # 消耗生成器以执行裁剪逻辑
        for _ in gen: pass
        
    # 历史记录应该被裁剪到上限
    assert len(llm_service.sessions[session_id]) <= LLM_MAX_HISTORY_TURNS * 2
    # 并且包含最后的一条回复（虽然这里 mock 返回空，但逻辑上应该保留）
    # 注意：在 stream_reply 中，裁剪是在追加新 user 消息后，API 调用前。
    # 裁剪后长度应为 max_msgs
