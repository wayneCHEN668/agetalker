import pytest
import numpy as np
from unittest.mock import patch, MagicMock
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.emotion_service import EmotionService, EmotionResult
from config import EMOTION_MIN_DURATION_S, EMOTION_CONF_THRESHOLD

@pytest.fixture
def svc():
    """Initialize EmotionService with mocked AutoModel."""
    with patch('services.emotion_service.AutoModel') as mock_cls:
        mock_cls.return_value = MagicMock()
        service = EmotionService()
        service.model = mock_cls.return_value
    return service

def make_audio(duration_s: float = 2.0) -> np.ndarray:
    """Generate Float32 sine wave test audio (16kHz)."""
    samples = int(16000 * duration_s)
    t = np.linspace(0, duration_s, samples)
    return (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)

def mock_scores(label: str, score: float) -> list:
    """Construct mock scores for model output."""
    all_labels = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']
    remaining = (1.0 - score) / (len(all_labels) - 1) if len(all_labels) > 1 else 0
    
    # Return formatted labels consistent with emotion2vec (e.g., 'happy/happy')
    return [
        {'label': f"{l}/{l}", 'score': score if l == label else remaining}
        for l in all_labels
    ]

def test_short_audio_returns_neutral(svc):
    """Verify short audio returns neutral without calling model."""
    short_audio = make_audio(0.3)
    result = svc.analyze(short_audio, "test_session")
    assert result.label == 'neutral'
    assert result.label_zh == '平静'
    svc.model.generate.assert_not_called()

def test_successful_analysis(svc):
    """Verify successful analysis returns EmotionResult dataclass."""
    audio = make_audio(2.0)
    svc.model.generate.return_value = [{'labels': ['happy/happy'], 'scores': [0.9], 'scores_all': mock_scores('happy', 0.9)}]
    # FunASR AutoModel actually returns a list of dicts. 
    # Let's adjust the mock to match the service's expectations.
    svc.model.generate.return_value = [{
        'labels': ['happy/happy'],
        'scores': [0.9]
    }]
    
    result = svc.analyze(audio, "test_session")
    assert isinstance(result, EmotionResult)
    assert result.label == 'happy'
    assert result.score == 0.9
    assert result.label_zh == '快乐'

def test_low_confidence_fallback(svc):
    """Verify low confidence result falls back to neutral."""
    audio = make_audio(2.0)
    svc.model.generate.return_value = [{
        'labels': ['angry/angry'],
        'scores': [EMOTION_CONF_THRESHOLD - 0.1]
    }]
    
    result = svc.analyze(audio, "test_session")
    assert result.label == 'neutral'
    assert result.raw_label == 'angry'

def test_multi_session_isolation(svc):
    """Verify that different sessions have separate histories."""
    audio = make_audio(2.0)
    
    # Session A: happy
    svc.model.generate.return_value = [{'labels': ['happy/happy'], 'scores': [0.9]}]
    svc.analyze(audio, "session_A")
    
    # Session B: sad
    svc.model.generate.return_value = [{'labels': ['sad/sad'], 'scores': [0.8]}]
    svc.analyze(audio, "session_B")
    
    assert svc.session_histories["session_A"][-1]["label"] == "happy"
    assert svc.session_histories["session_B"][-1]["label"] == "sad"

def test_to_dict_serialization(svc):
    """Verify to_dict returns correct dictionary format."""
    audio = make_audio(2.0)
    svc.model.generate.return_value = [{'labels': ['neutral/neutral'], 'scores': [1.0]}]
    result = svc.analyze(audio, "test_session")
    
    d = svc.to_dict(result)
    assert isinstance(d, dict)
    assert d['label'] == 'neutral'
    assert 'label_zh' in d
    assert 'valence' in d
    assert 'arousal' in d
    assert 'trend' in d
    assert 'history' in d
