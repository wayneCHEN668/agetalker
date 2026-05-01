import requests
import json

def test_llm_stream():
    url = "http://localhost:8050/llm/stream"
    payload = {
        "text": "你好，我今天有点累。",
        "emotion": {
            "label": "sad",
            "label_zh": "悲伤",
            "score": 0.8,
            "valence": 0.1,
            "arousal": 0.2,
            "trend": "stable"
        },
        "session_id": "debug_session"
    }
    
    print(f"Connecting to {url}...")
    try:
        response = requests.post(url, json=payload, stream=True)
        print(f"Status Code: {response.status_code}")
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                print(f"Received: {decoded_line}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_llm_stream()
