# STEP 4 — Speech Synthesis (TTS) Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a real-time emotional TTS system using Aliyun CosyVoice with a parallel sentence-based pipeline and echo cancellation.

**Architecture:** Merged FastAPI backend (Port 8050) providing PCM streams; React Native (Web) frontend using WebAudio API for low-latency playback and event-based ASR muting.

**Tech Stack:** FastAPI, Aliyun DashScope (CosyVoice), WebAudio API, React Hooks.

---

## Phase 1: Backend Implementation

### Task 1: Add TTS Configuration
**Files:**
- Modify: `backend/config.py`

**Step 1: Add TTS constants**
Add parameters for `TTS_MODEL`, `TTS_SAMPLE_RATE`, `TTS_EMOTION_VOICE_MAP`, etc.

### Task 2: Implement TTSService
**Files:**
- Create: `backend/services/tts_service.py`

**Step 1: Implement basic synthesis logic**
Create `TTSService` class with `synthesize_stream` method using `SpeechSynthesizer`.

### Task 3: Implement TTS Router
**Files:**
- Create: `backend/routers/stream_tts.py`

**Step 1: Define TTSRequest schema and /tts/stream endpoint**
Implement the POST endpoint returning `StreamingResponse`.

### Task 4: Main App Integration
**Files:**
- Modify: `backend/main.py`

**Step 1: Initialize TTSService in lifespan and include router**
Ensure `tts_service` is injected into the router module.

### Task 5: Backend Verification
**Files:**
- Create: `backend/selftest/test_tts.py`

**Step 1: Write and run synthesis test**
Verify that calling the service returns a non-empty byte stream.

---

## Phase 2: Frontend Implementation

### Task 6: Shared Constants & Types
**Files:**
- Create: `mobile/constants/TTS.ts`

**Step 1: Define TTS_PARAMS_MAP and Types**
Map emotions to speed, pitch, and style according to the "Healing Symmetry" design.

### Task 7: Implement useTTS Hook
**Files:**
- Create: `mobile/hooks/useTTS.ts`

**Step 1: Implement WebAudio playback and Queue**
Create a hook that fetches PCM from `/tts/stream` and plays it sequentially using `AudioContext`.

### Task 8: Update useLLM for Parallelism
**Files:**
- Modify: `mobile/hooks/useLLM.ts`

**Step 1: Add sentence detection**
Identify sentence boundaries and call `useTTS.speak()`.

### Task 9: Echo Cancellation in useASR
**Files:**
- Modify: `mobile/hooks/useASR.ts`

**Step 1: Listen for tts-start/tts-end and mute transmission**
Prevent microphone data from being sent while TTS is active.

---

## Phase 3: Final Polish & Verification

### Task 10: Full Chain Test
**Step 1: Manual end-to-end test**
Verify: Voice -> ASR -> LLM -> Sentence 1 -> TTS -> Audio -> ASR Resume.
