# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgeTalker is a voice-based AI companion for elderly users in nursing homes. It runs a 4-step pipeline: ASR (speech-to-text) → Emotion Recognition → LLM (psychological response) → TTS (emotion-aware voice synthesis).

## Architecture

**Monorepo** with two packages:

### Backend (`backend/`)
- **Framework**: Python FastAPI, single-worker (for model stability)
- **Entrypoint**: `main.py` — lifespan handler initializes services and injects them into routers
- **Config**: `config.py` — centralized config for all 4 pipeline steps
- **Services** (`services/`):
  - `asr_service.py` — FunASR `paraformer-zh` with VAD + punctuation model
  - `emotion_service.py` — emotion2vec_plus with temporal smoothing (weighted sliding window)
  - `llm_service.py` — Qwen via DashScope API, crisis keyword detection, multi-session history
  - `tts_service.py` — CosyVoice via DashScope, emotion-to-voice mapping ("healing symmetry")
- **Routers** (`routers/`):
  - `ws_asr.py` — WebSocket `/ws/asr` for real-time audio streaming
  - `sse_llm.py` — POST `/llm/stream` (SSE) for streaming LLM replies
  - `stream_tts.py` — POST `/tts/stream` for streaming PCM audio
- **Prompts** (`prompts/templates.py`): CARE framework system prompts with per-emotion strategies
- **Tests**: `selftest/` directory (pytest)

### Frontend (`mobile/`)
- **Framework**: React Native with Expo / Expo Router (file-based routing)
- **Entry screen**: `app/(tabs)/index.tsx` — orchestrates ASR → LLM → TTS pipeline
- **Hooks** (`hooks/`):
  - `useASR.ts` — WebSocket audio capture with echo cancellation (TTS-mute via window events)
  - `useLLM.ts` — SSE fetch with streaming text accumulation
  - `useTTS.ts` — WebAudio PCM playback with sequential queue
- **Components**: `ActionButton`, `Waveform`, `TranscriptArea`, `ResponseArea`, `StatusBar`
- **Design**: `constants/Design.ts` — warm sage-green palette, Lexend font, large typography optimized for elderly

### Key Design Decisions
- Runs entirely on **CPU** (no GPU dependencies)
- ASR silence threshold tuned for elderly speech pauses (~1.5s)
- TTS uses "healing symmetry": response voice style mirrors user's detected emotion
- LLM uses CARE framework (Connect → Acknowledge → Respond → Empower)
- Crisis detection via keyword matching triggers special intervention prompt
- Echo cancellation: ASR input is muted during TTS playback, with 200ms debounce

## Startup

| Component | Command | Port |
|-----------|---------|------|
| Backend | `cd backend && .venv\Scripts\activate && uvicorn main:app --reload --port 8050` | 8050 |
| Frontend Web | `cd mobile && npx expo start --web` | 8081 |
| Both (via root) | `npm run backend` / `npm run mobile` | — |

Helper batch files: `startend.bat` (backend), `startfront.bat` (mobile web).

## Testing

```bash
cd backend
.venv\Scripts\activate
pytest selftest/ -v
pytest selftest/test_llm_service.py -v           # single file
pytest selftest/test_llm_service.py::test_crisis_detection -v  # single test
```

## Environment

- Create `backend/.env` with `DASHSCOPE_API_KEY` (Aliyun DashScope/通义千问 API key)
- Python venv at `backend/.venv/` (pre-existing)
- Dependencies: `backend/requirements.txt` — includes funasr, torch (CPU), fastapi, openai, dashscope
- Mobile deps: `mobile/package.json` (Expo 52, React 19, expo-router)
