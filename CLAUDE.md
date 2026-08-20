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

## 本地模型缓存 / 部署

四个 ML 模型（ASR + VAD + PUNC + emotion2vec，共 ~3.9G）缓存在 `backend/.model_cache/models/iic/`。`config.py` 里的 `_local_or_hub()` 在启动时检查该目录：

- **目录存在** → 直接把绝对路径传给 funasr。`download_from_ms()` 的 `os.path.exists()` 命中后会跳过整个 ModelScope 流程，**启动不联网，断网也能起**。
- **目录不存在**（新服务器首次部署）→ 回落到模型 ID（`paraformer-zh` 等），自动下载到该目录，第二次启动起走本地。

部署注意：

- `.model_cache/` 已在 `.gitignore:10` 中排除，`git clone` 拿不到。**内网/无外网的服务器必须手动把这个目录传过去**，否则首次启动会卡在下载。
- 走本地路径后模型**不再自动更新**（这是有意的，省掉每次启动一次联网版本核对）。要升级模型：删掉对应子目录，下次启动会重新下载。
- `MODELSCOPE_CACHE` 在 `.env` 里是相对路径，`config.py` 会基于 `backend/` 转成绝对路径 —— 不要改回相对路径直接用，否则从仓库根目录启动会认到空目录并重下 3.9G。

## 已知失效的测试（重构遗留，非回归）

`selftest/` 里这几个是双后端重构（云端 ASR + 本地兜底）之前的产物，改任何代码前就已经是坏的，不要误判成自己弄坏的：

- `test_asr.py` / `test_emotion.py` / `test_model.py` — `ModuleNotFoundError: No module named 'asr_manager'`（模块已删）
- `test_refactor.py::test_config_loading` — 断言 `ASRService.model`，但 `.model` 现在在 `LocalASRBackend` 上
- `test_ws.py` / `test_tts.py` — 连真实服务，无服务端时会挂住，跑全量测试时需 `--ignore`

可离线跑的子集：`pytest selftest/test_emotion_refactored.py selftest/test_llm_service.py selftest/test_sentence_merge.py -q`

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

## 在 worktree 里干活时：构建/验证一定要确认目录

`.worktrees/` 下的分支和主仓库 checkout 是**两份独立的代码**。这一点在本项目已经坑过两次，
两次都表现为「验证结果看着正常/异常，但验的根本不是你改的代码」：

1. **构建装机装错源**：从主仓库跑 `gradlew assembleDebug` + `adb install`，装上去的是 master
   的旧代码。症状极具迷惑性——APP 能跑、大部分页面正常，只有你改的那个功能"没反应"，
   看起来像新代码有 bug，实际上新代码压根没被编译进去。
   **快速判别**：`adb shell dumpsys package <包名> | grep -A5 "requested permissions"`
   对比 worktree 里 `android/app/src/main/AndroidManifest.xml` 的权限声明。对不上就是装错了。
2. **dev server 起错目录**：`preview_start` 用 `.claude/launch.json` 里的相对 `cwd`，
   解析基准是**主仓库**，不是当前 worktree。Metro 缓存还在 `%TEMP%\metro-cache`（全局、
   跨 worktree 共用），会让"改了没生效"更难看出来。

规矩：

- 构建、装机、起 dev server 前，**先 `pwd` 确认在 worktree 里**，用绝对路径，别依赖相对 cwd。
- 起 web 调试用 `cd <worktree>/mobile && npx expo start --web`，不要用 `preview_start` 的
  `name` 形式（它会指向主仓库）；要用 Browser 工具就用 `preview_start` 的 `url` 形式接
  手动起好的服务。
- 怀疑"改了没生效"时，先查是不是缓存/目录问题，再怀疑代码。`npx expo start --web -c`
  强制清 Metro 缓存。

## 调试
**UPDATE CLAUDE.MD, ADD RULES FOR ANY NEW MISTAKES