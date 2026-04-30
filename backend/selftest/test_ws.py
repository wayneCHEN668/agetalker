import pytest
import json
import numpy as np
from fastapi.testclient import TestClient
import os
import sys

# Add backend directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_websocket_connection():
    with client.websocket_connect("/ws/asr") as websocket:
        # Should receive status message first
        data = websocket.receive_text()
        msg = json.loads(data)
        assert msg["type"] == "status"
        assert msg["state"] == "listening"
        
        # Send some dummy silent audio (PCM 16-bit 100ms)
        dummy_audio = np.zeros(1600, dtype=np.int16).tobytes()
        websocket.send_bytes(dummy_audio)
        
        # Send more silence
        for _ in range(10):
            websocket.send_bytes(dummy_audio)
        
        # We don't expect a transcript for pure silence
        # But we check that the connection is still open
        websocket.close()

def test_audio_processing_flow():
    """Simulate a short audio clip sending to WS."""
    with client.websocket_connect("/ws/asr") as websocket:
        websocket.receive_text() # status: listening
        
        # Send 1s of "signal" (sine wave)
        # Note: Paraformer won't transcribe a sine wave into text, but VAD should trigger
        audio_int16 = (np.sin(np.linspace(0, 2*np.pi*440, 16000)) * 32767).astype(np.int16)
        websocket.send_bytes(audio_int16.tobytes())
        
        # Send 2s of silence to trigger VAD
        silence = np.zeros(32000, dtype=np.int16).tobytes()
        websocket.send_bytes(silence)
        
        # Should receive status: processing
        msg = json.loads(websocket.receive_text())
        assert msg["type"] == "status"
        assert msg["state"] == "processing"
        
        # Should eventually receive status: listening again
        # Even if transcript is empty
        msg = json.loads(websocket.receive_text())
        assert msg["type"] == "status"
        assert msg["state"] == "listening"
        
        websocket.close()
