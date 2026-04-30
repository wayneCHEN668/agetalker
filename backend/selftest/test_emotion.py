# e:\MyDoc\APP\agetalker\backend\selftest\test_emotion.py

import sys
import os
import pytest
import numpy as np
from unittest.mock import MagicMock, patch

# Add parent dir to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emotion_manager import EmotionManager
from config import HISTORY_WEIGHTS, EMOTION_COORDS

class TestEmotionLogic:
    
    @pytest.fixture
    def mock_manager(self):
        with patch('emotion_manager.AutoModel') as mock_model:
            manager = EmotionManager()
            # Mock the generate method
            manager.model.generate = MagicMock()
            return manager

    def test_label_normalization(self, mock_manager):
        """TC-01: Verify mapping of various labels to standard English."""
        assert mock_manager._normalize_label('开心') == 'happy'
        assert mock_manager._normalize_label('悲伤') == 'sad'
        assert mock_manager._normalize_label('unknown_tag') == 'neutral'
        assert mock_manager._normalize_label('joy') == 'happy'

    def test_smoothing_logic(self, mock_manager):
        """TC-02: Verify weighted smoothing over 3 rounds."""
        session_id = "test_user_01"
        
        # Round 1: Happy (0.8)
        # Votes: {happy: 0.8 * 0.5} = 0.4
        res1 = mock_manager._smooth(session_id, 'happy', 0.8)
        assert res1['label'] == 'happy'
        mock_manager._get_history(session_id).append({'label': 'happy', 'score': 0.8})
        
        # Round 2: Angry (0.6)
        # Votes: {angry: 0.6 * 0.5 (0.3), happy: 0.8 * 0.3 (0.24)}
        res2 = mock_manager._smooth(session_id, 'angry', 0.6)
        assert res2['label'] == 'angry' # 0.3 > 0.24
        mock_manager._get_history(session_id).append({'label': 'angry', 'score': 0.6})
        
        # Round 3: Happy (0.5)
        # Votes: 
        # happy: 0.5 * 0.5 (0.25) + 0.8 * 0.2 (0.16) = 0.41
        # angry: 0.6 * 0.3 (0.18)
        # Winner: happy
        res3 = mock_manager._smooth(session_id, 'happy', 0.5)
        assert res3['label'] == 'happy'
        assert res3['score'] == 0.41

    def test_trend_calculation(self, mock_manager):
        """TC-03: Verify trend description."""
        session_id = "test_user_02"
        
        # Initial
        assert "建立情绪基准" in mock_manager._get_trend(session_id, 'neutral')
        
        # Neutral -> Happy
        mock_manager._get_history(session_id).append({'label': 'neutral', 'score': 1.0})
        trend = mock_manager._get_trend(session_id, 'happy')
        assert "情绪好转" in trend
        
        # Happy -> Sad
        mock_manager._get_history(session_id).append({'label': 'happy', 'score': 1.0})
        trend = mock_manager._get_trend(session_id, 'sad')
        assert "情绪回落" in trend

    def test_confidence_filter_integration(self, mock_manager):
        """TC-04: Verify low confidence results are downgraded to neutral."""
        session_id = "test_user_03"
        
        # Mock model returning low confidence 'angry' (0.3) in the ACTUAL format
        mock_manager.model.generate.return_value = [{
            'labels': ['愤怒/angry', '平静/neutral'],
            'scores': [0.3, 0.2]
        }]
        
        audio = np.zeros(16000, dtype=np.int16) # 1s silence
        result = mock_manager.analyze(audio, session_id)
        
        assert result['label'] == 'neutral'
        assert result['raw']['label'] == 'angry'
        assert result['raw']['score'] == 0.3

if __name__ == "__main__":
    pytest.main([__file__])
