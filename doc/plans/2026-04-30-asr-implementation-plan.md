# ASR Module Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a real-time Chinese ASR system with a Python backend and a React Native (Expo) frontend, optimized for seniors with the specific visual layout provided.

**Architecture:** Monorepo structure with a FastAPI backend running FunASR models and an Expo mobile app for the UI. Communication via WebSockets for low-latency PCM streaming.

**Tech Stack:** Python (FastAPI, FunASR), React Native (Expo, TypeScript), WebSockets.

---

### Task 1: Project Initialization & Environment Setup

**Files:**
- Create: `package.json` (Root)
- Create: `backend/requirements.txt`
- Create: `backend/.env`

**Step 1: Initialize Root package.json**
```json
{
  "name": "agetalker",
  "private": true,
  "scripts": {
    "backend": "cd backend && uvicorn main:app --reload",
    "mobile": "cd mobile && npx expo start"
  }
}
```

**Step 2: Setup Python Virtual Environment**
Run: `python -m venv backend/.venv`
Run: `backend/.venv/Scripts/activate`

**Step 3: Define Backend Requirements**
```text
funasr>=1.1.0
torch --index-url https://download.pytorch.org/whl/cpu
torchaudio --index-url https://download.pytorch.org/whl/cpu
fastapi
uvicorn[standard]
numpy
python-dotenv
```

**Step 4: Commit Initialization**
```bash
git add .
git commit -m "chore: initialize monorepo and backend requirements"
```

---

### Task 2: Backend ASR Core Implementation (TDD)

**Files:**
- Create: `backend/asr_manager.py`
- Create: `backend/selftest/test_asr.py`
- Create: `backend/hotwords.txt`

**Step 1: Write failing test for audio conversion**
```python
import numpy as np
from asr_manager import bytes_to_float32

def test_bytes_to_float32():
    data = np.array([32767, -32768], dtype=np.int16).tobytes()
    result = bytes_to_float32(data)
    assert np.allclose(result, [1.0, -1.0], atol=1e-4)
```

**Step 2: Implement ASRManager and conversion**
```python
import numpy as np
from funasr import AutoModel

def bytes_to_float32(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

class ASRManager:
    def __init__(self):
        self.model = AutoModel(model='paraformer-zh', vad_model='fsmn-vad', punc_model='ct-punc', device='cpu')
```

**Step 3: Verify tests and Commit**
Run: `pytest backend/selftest/test_asr.py`
```bash
git add backend/
git commit -m "feat: implement core asr utility and model loading"
```

---

### Task 3: WebSocket ASR Service

**Files:**
- Create: `backend/main.py`
- Create: `backend/selftest/test_ws.py`

**Step 1: Implement WebSocket endpoint with VAD logic**
```python
@app.websocket("/ws/asr")
async def asr_socket(websocket: WebSocket):
    await websocket.accept()
    buffer = []
    # Implement VAD silence detection (1.5s) and inference call
```

**Step 2: Commit Backend Service**
```bash
git add backend/main.py
git commit -m "feat: add websocket endpoint for real-time asr"
```

---

### Task 4: Mobile App Setup & Design System

**Files:**
- Create: `mobile/` (via `npx create-expo-app`)
- Modify: `mobile/app.json` (Add Lexend font)
- Create: `mobile/constants/Colors.ts`

**Step 1: Initialize Expo App**
Run: `npx create-expo-app@latest mobile --template tabs`

**Step 2: Implement Design System Tokens**
Create `mobile/constants/Design.ts` based on `doc/Design.md` and the user's visual layout.

**Step 3: Setup Lexend Font**
Run: `npx expo install expo-font @expo-google-fonts/lexend`

**Step 4: Commit Mobile Base**
```bash
git add mobile/
git commit -m "feat: initialize expo mobile app with design tokens"
```

---

### Task 5: UI Implementation (Laptop-First)

**Files:**
- Create: `mobile/components/StatusBar.tsx`
- Create: `mobile/components/TranscriptArea.tsx`
- Create: `mobile/components/Waveform.tsx`
- Create: `mobile/components/ActionButton.tsx`
- Create: `mobile/components/ResponseArea.tsx`

**Step 1: Build the specific UI layout provided by user**
Implement the stacked layout (Status -> Transcript -> Waveform -> Response -> Button).

**Step 2: Add animations**
Add pulse animation for the Microphone button and typewriter effect for ResponseArea.

**Step 3: Commit UI Components**
```bash
git add mobile/components/
git commit -m "feat: implement complete UI layout with animations"
```

---

### Task 6: Real-time Audio & Final Polish

**Files:**
- Create: `mobile/hooks/useASR.ts`

**Step 1: Implement useASR hook**
Adapt for Web/Mobile PCM capture and WebSocket streaming.

**Step 2: End-to-End Verification**
Run full stack on laptop and verify transcription latency.

**Step 3: Final Commit**
```bash
git add .
git commit -m "feat: complete agetalker ASR module integration"
```
