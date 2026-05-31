# OpenAI voice architecture check — 2026-05-31

## Question

Tailchat already has a local Hermes text-agent flow. Voice should add browser microphone input and spoken output without bypassing Hermes as the agent of record.

## Official OpenAI references checked

- `https://developers.openai.com/api/docs/guides/voice-agents.md`
- `https://developers.openai.com/api/docs/guides/realtime.md`
- `https://developers.openai.com/api/docs/guides/realtime-transcription.md`
- `https://developers.openai.com/api/docs/guides/realtime-webrtc.md`
- `https://developers.openai.com/api/docs/guides/text-to-speech.md`
- `https://developers.openai.com/api/docs/guides/latest-model.md`

## Decision

Use OpenAI's **chained voice pipeline** pattern, not a Realtime voice-agent session, because Tailchat already has Hermes as the text agent and needs explicit visibility/control between stages.

Pipeline:

1. Browser microphone → OpenAI Realtime transcription session.
2. Completed transcript → Tailchat `/api/conversations/{id}/messages`.
3. Tailchat/Hermes runs the normal text turn with existing approvals/history/events.
4. Completed Hermes response → Tailchat backend `/api/realtime/speech`.
5. Backend calls OpenAI Audio Speech API and returns audio to the browser for playback.

## Model choices

- Live STT: `gpt-realtime-whisper`.
  - Official realtime transcription docs describe it as the lowest-latency streaming transcription path for live audio and transcript deltas.
- TTS: `gpt-4o-mini-tts`.
  - Official TTS docs describe it as the newest and most reliable text-to-speech model.
- Hermes text reasoning: leave to the Hermes provider/gateway configuration. The OpenAI latest-model guide identifies `gpt-5.5` as current latest for complex production workflows, but Tailchat should not hard-code that inside the voice bridge; it should stay provider-configured.

## Rejected architecture

A `gpt-realtime-2` voice-agent session with automatic or manually-created responses is a poorer fit here. It can create a second agent loop outside Hermes, blurring responsibility for tools, approvals, durable transcript, and conversation state. It is best when the Realtime model is the agent. Tailchat's product contract is that Hermes is the agent.

## Security / operational notes

- Browser still receives only ephemeral Realtime client secrets, not the long-lived OpenAI API key.
- TTS uses a backend endpoint because the Audio Speech API requires server-side authentication.
- Safety identifiers remain hashed per conversation and are set by the backend.
