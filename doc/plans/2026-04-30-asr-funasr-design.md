# ASR Module Design (FunASR + React Native/Expo)

**Date**: 2026-04-30
**Status**: Validated (Updated with UI Layout)

## Overview
This design outlines a real-time speech-to-text module for an elderly companion application. It uses a Python-based ASR backend and a cross-platform mobile frontend.

## Architecture
- **Monorepo Structure**:
  - `/backend`: FastAPI + FunASR (paraformer-zh, fsmn-vad, ct-punc).
  - `/mobile`: React Native + Expo (Web-first for laptop testing).

## Technical Approach

### Backend (ASR Service)
- **Singleton Model Loading**: Models loaded once at startup.
- **WebSocket Protocol**: Real-time 16kHz PCM audio streaming.
- **Elderly-Optimized VAD**: 1500ms silence threshold to accommodate slower speech.
- **Hotwords**: Scene-specific terms (e.g., "养老院", "用药时间") injected for higher accuracy.

### Frontend (Mobile App)
- **Framework**: Expo (React Native).
- **Audio Capture**: 16kHz Mono PCM capture.
- **UI Layout**: 
  - **Status Bar (Top)**: "正在聆听..." with dynamic pulses.
  - **Transcript Area**: Scrolling text area for user speech with emotion tags.
  - **Waveform Animation**: Centered Canvas-based wave reflecting audio intensity.
  - **LLM Response Area**: Typewriter-effect text for AI responses.
  - **Primary Action Button (Bottom)**: Large "开始对话" button with pulse animation (toggles to "挂断").

## Data Flow
1. Mobile app captures audio and streams PCM chunks via WebSocket.
2. Backend processes chunks, detects sentence boundaries via VAD.
3. Backend transcribes audio using Paraformer and adds punctuation.
4. Backend sends JSON transcript back to Mobile app.

## Testing Strategy
- **Laptop-First**: Expo Web target for easy browser-based testing.
- **TDD**: Pytest for backend logic; Jest for frontend state and components.
- **Integration**: Automated scripts simulating audio playback to the WebSocket endpoint.
