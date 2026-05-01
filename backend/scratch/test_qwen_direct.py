import sys
import os
# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.llm_service import LLMService

def test_direct_qwen():
    try:
        svc = LLMService()
        print("Initialized service...")
        text = "你好"
        emotion = {"label": "neutral", "label_zh": "平静", "score": 1.0, "valence": 0.5, "arousal": 0.2}
        
        print("Calling stream_reply...")
        gen = svc.stream_reply(text, emotion)
        for chunk in gen:
            print(f"Chunk: {chunk}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_direct_qwen()
