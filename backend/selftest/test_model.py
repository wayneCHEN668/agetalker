import pytest
import numpy as np
import os
import sys

# Add backend directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asr_manager import get_asr_manager

@pytest.mark.skipif(os.environ.get("SKIP_MODEL_TESTS") == "1", reason="Skipping model tests")
def test_model_loading_and_inference():
    """Test loading the actual models and running a simple inference on zero audio."""
    mgr = get_asr_manager()
    assert mgr.asr_model is not None
    
    # Run inference on 1s of silence (16000 samples)
    audio = np.zeros(16000, dtype=np.float32)
    result = mgr.transcribe(audio)
    
    # Should return empty string for silence
    assert isinstance(result, str)
    assert result == ""
