import pytest
import numpy as np
import os
import sys

# Add backend directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asr_manager import bytes_to_float32, ASRManager

def test_bytes_to_float32():
    """Test converting Int16 PCM bytes to normalized Float32."""
    # 0, 32767, -32768, 16384
    int16_data = np.array([0, 32767, -32768, 16384], dtype=np.int16)
    data_bytes = int16_data.tobytes()
    
    result = bytes_to_float32(data_bytes)
    
    assert result.dtype == np.float32
    assert len(result) == 4
    assert result[0] == 0.0
    assert np.isclose(result[1], 32767.0 / 32768.0, atol=1e-5)
    assert result[2] == -1.0
    assert np.isclose(result[3], 0.5, atol=1e-5)

def test_compute_rms():
    """Test RMS calculation for silence and signal."""
    from asr_manager import compute_rms
    
    silence = np.zeros(1600, dtype=np.float32)
    assert compute_rms(silence) < 0.0001
    
    signal = np.sin(np.linspace(0, 2 * np.pi, 1600)).astype(np.float32) * 0.5
    assert compute_rms(signal) > 0.3 # RMS of sine wave with amp 0.5 is approx 0.35
