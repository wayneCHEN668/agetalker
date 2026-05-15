import os
import sys
import pytest

# Add parent directory to sys.path to import config and services
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.tts_service import TTSService

def test_tts_service_init():
    """Verify TTSService initializes correctly."""
    service = TTSService()
    assert service.is_playing is False

def test_tts_synthesis_stream():
    """Verify that synthesize_stream yields bytes."""
    service = TTSService()
    text = "测试语音合成。这是第一句。这是第二句。"
    
    # We only take a small chunk to avoid excessive API usage/costs in tests
    generator = service.synthesize_stream(text=text)
    
    try:
        first_chunk = next(generator)
        assert isinstance(first_chunk, bytes)
        assert len(first_chunk) > 0
    except StopIteration:
        pytest.fail("Generator yielded nothing")
    except Exception as e:
        pytest.fail(f"TTS Synthesis failed: {e}")
    finally:
        # Cleanup: generator might still be open
        generator.close()

def test_tts_sentence_splitting():
    """Verify text is correctly split into sentences."""
    service = TTSService()
    text = "你好。今天天气不错！我们去公园吗？好的。"
    sentences = service._split_sentences(text)
    
    assert len(sentences) == 4
    assert sentences[0] == "你好。"
    assert sentences[1] == "今天天气不错！"
    assert sentences[2] == "我们去公园吗？"
    assert sentences[3] == "好的。"

if __name__ == "__main__":
    # Manual run support
    svc = TTSService()
    print("Testing sentence splitting...")
    print(svc._split_sentences("你好。我在这里陪着您。"))
    
    print("\nTesting stream synthesis (fetching 1 chunk)...")
    for chunk in svc.synthesize_stream("测试一下。"):
        print(f"Received chunk of size: {len(chunk)}")
        break
    print("Test finished.")
