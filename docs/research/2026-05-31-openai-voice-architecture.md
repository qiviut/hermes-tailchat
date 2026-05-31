# OpenAI voice architecture check — 2026-05-31

## Question

Tailchat already has a local Hermes text-agent flow. Voice should add browser microphone input and spoken output without bypassing Hermes as the agent of record.

## Official OpenAI references checked

- `https://developers.openai.com/api/docs/guides/voice-agents.md`
- `https://developers.openai.com/api/docs/guides/realtime.md`
- `https://developers.openai.com/api/docs/guides/realtime-transcription.md`
- `https://developers.openai.com/api/docs/guides/realtime-webrtc.md`
- `https://developers.openai.com/api/docs/guides/realtime-mcp.md`
- `https://developers.openai.com/api/docs/guides/text-to-speech.md`
- `https://developers.openai.com/api/docs/guides/latest-model.md`

## Decision

Use a **Realtime voice-agent session with a single Hermes function tool**.

This is the best fit for Tailchat because it combines:

- Realtime voice UX: turn taking, barge-in, low first-audio latency, and short wait-state speech.
- Hermes authority: every substantive user request is routed through Tailchat's normal Hermes message/run/approval/history flow.

The earlier pure chained pipeline was safe, but too stiff: Realtime only transcribed and Tailchat used separate TTS. The better boundary is to let Realtime be the voice controller while making Hermes the only substantive tool.

## Pipeline

1. Browser opens an OpenAI Realtime WebRTC session using a backend-minted ephemeral client secret.
2. Session is configured as `type: "realtime"`, `model: "gpt-realtime-2"`, audio output enabled, and tool choice `auto`.
3. The session exposes one function tool: `run_hermes_turn({ request })`.
4. Realtime may say short status/filler such as “let me check with Hermes,” but instructions forbid substantive answers without the tool.
5. When Realtime emits `response.function_call_arguments.done`, the browser posts the request to Tailchat `/api/conversations/{id}/messages`.
6. Tailchat/Hermes runs normally: provider config, approvals, events, persistence, and session linkage remain unchanged.
7. When Tailchat SSE emits `message.completed` for that `run_id`, the browser sends `conversation.item.create` with `type: "function_call_output"` and then `response.create` back to Realtime.
8. Realtime speaks the Hermes result.

## Model choices

- Voice-agent shell: `gpt-realtime-2`.
  - OpenAI's Realtime overview describes voice-agent sessions as the path when the model should respond, call tools, and manage conversation state.
- Live input transcription inside the voice session: `gpt-realtime-whisper`.
  - Official realtime transcription docs describe it as the low-latency streaming transcription path for live audio and transcript deltas.
- Optional backend TTS fallback remains `gpt-4o-mini-tts`, but the active voice-agent path speaks through the Realtime session.
- Hermes text reasoning remains controlled by Hermes provider/gateway configuration. Tailchat should not hard-code the text model inside the voice bridge.

## Rejected architectures

- **Realtime answers directly:** too much authority leaks to a second agent outside Hermes.
- **Pure transcription → Hermes → TTS chain:** safe and explicit, but loses Realtime's natural wait-state, interruption, and tool-call UX.
- **Hybrid Realtime voice-agent plus ad hoc Hermes response injection:** muddy unless Hermes is represented as a formal function tool with tool-call output.

## Security / operational notes

- Browser receives only ephemeral Realtime client secrets, not the long-lived OpenAI API key.
- Safety identifiers remain hashed per conversation and are set by the backend.
- Realtime instructions are a UX boundary, not a security boundary; Tailchat/Hermes remains the authoritative tool executor and approval gate.
- Diagnostics must continue redacting keys, SDP, tokens, and Authorization headers.
