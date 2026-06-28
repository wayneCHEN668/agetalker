# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgeTalker is a voice-based AI companion for elderly users in nursing homes. It runs a 4-step pipeline: ASR (speech-to-text) → Emotion Recognition → LLM (psychological response) → TTS (emotion-aware voice synthesis).

## Architecture

**Monorepo** with two packages:

### Backend (`backend/`)
- **Framework**: Python FastAPI, single-worker (for model stability)
- **Entrypoint**: `main.py` — lifespan handler initializes services and injects them into routers
- **Config**: `config.py` — centralized config for all 4 pipeline steps, plus router model settings
- **Services** (`services/`):
  - `asr_service.py` — FunASR `paraformer-zh` with VAD + punctuation model
  - `emotion_service.py` — emotion2vec_plus with temporal smoothing (weighted sliding window)
  - `llm_service.py` — Two-model architecture:
    - **Router (DeepSeek)**: Lightweight classification model that determines psychological category and selects a specific intervention strategy per turn. Low-temperature, low-latency, separate client/endpoint from the main generator.
    - **Generator (Qwen via DashScope)**: Main conversational model that produces the actual reply, guided by the category + strategy chosen by the router.
    - Crisis detection via keyword matching (hard circuit-breaker, 0ms latency) with router-level `is_crisis` as a second semantic layer.
    - Multi-session history with **strategy continuity** (tracks which strategies have been used per-category per-session) and **category continuity** (prevents mid-narrative neutral sentences from resetting the category).
  - `tts_service.py` — CosyVoice via DashScope, emotion-to-voice mapping ("healing symmetry")
- **Routers** (`routers/`):
  - `ws_asr.py` — WebSocket `/ws/asr` for real-time audio streaming
  - `sse_llm.py` — POST `/llm/stream` (SSE) for streaming LLM replies (async generator)
  - `stream_tts.py` — POST `/tts/stream` for streaming PCM audio
- **Prompts** (`prompts/templates.py`): CARE framework system prompts with per-category+strategy templates, plus router system/user prompt builders (`ROUTER_SYSTEM_PROMPT`, `build_router_user_prompt`, `CATEGORY_STRATEGY_MAP`, `resolve_strategy_id`)
- **Data** (`data/`): Runtime event files, including `crisis_events/` — JSON crisis alert files for external monitoring
- **Tests**: `selftest/` directory (pytest)

### Frontend (`mobile/`)
- **Framework**: React Native with Expo / Expo Router (file-based routing)
- **Entry screen**: `app/(tabs)/index.tsx` — orchestrates ASR → LLM → TTS pipeline
- **Hooks** (`hooks/`):
  - `useASR.ts` — WebSocket audio capture with echo cancellation (TTS-mute via window events)
  - `useLLM.ts` — SSE fetch with streaming text accumulation; captures backend-computed TTS params, category, and strategy name from the SSE `done` event
  - `useTTS.ts` — WebAudio PCM playback with sequential queue; accepts `TTSParams` directly from the backend (single source of truth, no client-side param duplication)
- **Components**: `ActionButton`, `Waveform`, `TranscriptArea` (shows emotion + category tags), `ResponseArea` (shows strategy name badge), `StatusBar`
- **Constants**:
  - `Design.ts` — warm sage-green palette, Lexend font, large typography optimized for elderly
  - `Category.ts` — maps backend psychological category keys to Chinese display names (depression, anxiety, anger, loneliness, grief, positive, neutral, crisis)
  - `TTS.ts` — TTS config (sample rate, channels) and `TTSParams` interface; no longer maintains a duplicate params map

### Key Design Decisions
- Runs entirely on **CPU** (no GPU dependencies) — all ML models (ASR, emotion) are CPU-only; LLM and TTS are API-based
- **Two-model LLM architecture**: Router (DeepSeek, fast/cheap) classifies psychological category and picks strategy; Generator (Qwen, high-quality) writes the reply. Separate API clients, independent failure modes.
- **Semantic-driven TTS**: TTS parameters are determined by the router's psychological category (not acoustic emotion label), via `CATEGORY_TTS_PARAMS_MAP`. Flows from backend to frontend through the SSE `done` event — backend is the single source of truth.
- **Strategy continuity**: The router tracks which strategies have been used per-category per-session, enabling multi-turn therapeutic progression rather than isolated per-turn choices.
- **Category continuity**: `last_category` state prevents the router from resetting to `neutral` on mid-narrative neutral sentences (asymmetric entry/exit thresholds).
- ASR silence threshold tuned for elderly speech pauses (~1.5s)
- TTS uses "healing symmetry": response voice style mirrors user's detected emotional state
- LLM uses CARE framework (Connect → Acknowledge → Respond → Empower)
- Crisis detection via keyword matching triggers special intervention prompt; router `is_crisis` acts as a second semantic safety layer
- Crisis events are logged (structured + JSON files in `data/crisis_events/`) for external monitoring/notification systems
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

- Create `backend/.env` with:
  - `DASHSCOPE_API_KEY` — Aliyun DashScope (Qwen main generator + CosyVoice TTS)
  - `DEEPSEEK_API_KEY` — DeepSeek API (router/classification model; falls back to `neutral` category if missing)
  - Optional: `QWEN_MODEL` (default `qwen-plus`), `DEEPSEEK_MODEL` (default `deepseek-v4-flash`), `DEEPSEEK_BASE_URL`
- Python venv at `backend/.venv/` (pre-existing)
- Dependencies: `backend/requirements.txt` — includes funasr, torch (CPU), fastapi, openai, dashscope
- Mobile deps: `mobile/package.json` (Expo 52, React 19, expo-router)

## Using Superpower wwriting-plan skill to Write Long Files

**Do NOT use default approach to write the plan, it always return Error 'writing file'

**Do NOT use Bash heredoc to write long markdown/plan files.** Heredocs with embedded code (Python, SQL, JS) fail due to quote conflicts and special character escaping. The `Write` tool is unreliable for long content (parameter-stripping bug).

**Reliable approach:** Write a Python generator script (using the `Write` tool since `.py` files are short) that constructs the content as a triple-quoted Python string and writes it to disk, then execute it with `python gen_script.py`. This avoids all escaping issues because Python triple-quoted raw strings (`r'''...'''`) handle quotes, backticks, and special characters natively. After execution, delete the generator script.

## 依赖库的安装
**Python依赖库必须安装在虚拟环境中

## 实现备忘录
**Implement <SPEC>. As you work maintaina running implementation-notes.html file that captures anything I should knowabout how the implementation diverges from or interprets the spec, including:
- Design decisions: choices you made where the spec was ambiguous
- Deviations: places where you intentionally departed from the spec, and why
- Tradeoffs: alternatives you considered and why you picked what you did
- Open questions: anything you'd want m¥e to confirm or revise

## 调试
**UPDATE CLAUDE.MD, ADD RULES FOR ANY NEW MISTAKES