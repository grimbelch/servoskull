# Future Improvements & Feature Backlog

## 🎙️ Audio & Voice Capabilities

- [ ] **Full-Duplex Voice & Real-Time Interruption (Barge-In)**
  - **Concept**: Allow continuous real-time listening while the assistant is actively speaking or processing audio, enabling natural conversation and instant user interruption.
  - **Acoustic Echo Cancellation (AEC)**: Enable PipeWire `module-echo-cancel` (`aec_source`) on the Raspberry Pi so speaker playback is subtracted from microphone input in real time.
  - **Background Silero VAD**: Run a lightweight Silero VAD (ONNX) thread checking 30ms mic audio buffers for human speech (`confidence > 0.8`).
  - **Instant Interruption**: When user speech is detected while the assistant is speaking, immediately cut off TTS playback (`audio.stop_playback()`), transition the screen to listening mode, and capture the new user prompt.
  - **Streaming Pipeline**: Stream LLM tokens sentence-by-sentence to ElevenLabs WebSocket TTS API to reduce end-to-end voice latency to under 500ms.

---
