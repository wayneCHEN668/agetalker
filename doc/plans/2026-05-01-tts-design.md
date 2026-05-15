# STEP 4 — Speech Synthesis (TTS) Design Document

**Date**: 2026-05-01
**Status**: Validated
**Scope**: Backend (FastAPI) & Frontend (React Native Expo Web)

## 1. Overview
This module converts LLM response text into emotional speech using the Aliyun CosyVoice API. It features a parallel pipeline to minimize latency and a global event-based echo cancellation system to prevent AI self-feedback.

## 2. Architecture
The system follows a merged architecture on **Port 8050**.

### 2.1 Backend (Python/FastAPI)
- **Service**: `TTSService` (Singleton) in `backend/services/tts_service.py`.
- **Router**: `stream_tts.py` in `backend/routers/stream_tts.py`.
- **Protocol**: Streaming PCM (24kHz, 16-bit, Mono) via HTTP `POST`.

### 2.2 Frontend (React Native / Expo Web)
- **Hooks**:
    - `useTTS.ts`: Manages playback queue and WebAudio `AudioContext`.
    - `useLLM.ts`: Updated to detect sentence boundaries and trigger TTS.
    - `useASR.ts`: Updated to listen for `tts-start`/`tts-end` to mute microphone.
- **Data Flow**:
    1. `useLLM` receives SSE stream.
    2. `useLLM` detects sentence -> `useTTS.speak(sentence)`.
    3. `useTTS` looks up `TTS_PARAMS_MAP` -> `POST /tts/stream`.
    4. `useTTS` plays PCM chunks.

## 3. Key Engineering Features

### 3.1 Pipeline Parallelism
TTS starts as soon as the **first sentence** is completed by the LLM. The frontend identifies sentence boundaries using regex `/[。！？.!?]/`.

### 3.2 Healing Symmetry (Emotion Mapping)
TTS parameters are determined by the emotion label identified in STEP 2.
- `sad` -> Gentle, slow.
- `angry` -> Calm, soft.
- `happy` -> Cheerful.
- `_crisis` -> Ultra-slow, gentle.

### 3.3 Echo Cancellation
- **`tts-start` event**: Mutes ASR transmission.
- **`tts-end` event**: Starts a **200ms timer** before unmuting ASR to allow room reverb to clear.

## 4. Testing & Verification
- **Unit Tests**: `backend/selftest/test_tts.py` for API connectivity.
- **Integration Tests**: Verification of `AudioContext` lifecycle and event propagation in the browser console.
