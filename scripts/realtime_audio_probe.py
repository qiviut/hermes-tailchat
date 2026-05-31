#!/usr/bin/env python3
"""Real OpenAI audio probe for Tailchat Realtime/STT plumbing.

Creates deterministic spoken audio locally with ffmpeg/flite, then validates:
1. synchronous request/response transcription via /v1/audio/transcriptions
2. asynchronous streaming transcription via Realtime WebSocket events

All output is JSONL/JSON and redacts credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any

import httpx
import websockets

DEFAULT_TEXT = "Purple banana audio probe confirms the microphone path."
ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "realtime-audio-probes"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def emit(phase: str, **data: Any) -> None:
    data = redact(data)
    print(json.dumps({"ts": time.time(), "phase": phase, **data}, ensure_ascii=False), flush=True)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        value = re.sub(r"sk-[A-Za-z0-9_\-]+", "sk-[REDACTED]", value)
        value = re.sub(r"ek_[A-Za-z0-9_\-]+", "ek_[REDACTED]", value)
        return value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if any(s in str(k).lower() for s in ("authorization", "api_key", "secret")):
                out[k] = "[REDACTED]"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def normalize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def match_score(expected: str, actual: str) -> dict[str, Any]:
    expected_tokens = normalize(expected)
    actual_tokens = normalize(actual)
    actual_set = set(actual_tokens)
    required = ["purple", "banana", "audio", "probe", "microphone", "path"]
    found_required = [t for t in required if t in actual_set]
    found_expected = [t for t in expected_tokens if t in actual_set]
    return {
        "expected_tokens": expected_tokens,
        "actual_tokens": actual_tokens,
        "required_found": found_required,
        "required_total": len(required),
        "expected_found_count": len(found_expected),
        "expected_total": len(expected_tokens),
        "pass": len(found_required) >= 5 and len(found_expected) >= max(5, int(len(expected_tokens) * 0.7)),
    }


def generate_audio(text: str, wav_path: Path, pcm_path: Path) -> None:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"flite=text={text}:voice=slt",
        "-ar",
        "24000",
        "-ac",
        "1",
        "-sample_fmt",
        "s16",
        "-y",
        str(wav_path),
    ]
    subprocess.run(cmd, check=True)
    subprocess.run([
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(wav_path),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "24000",
        "-ac",
        "1",
        "-y",
        str(pcm_path),
    ], check=True)
    with wave.open(str(wav_path), "rb") as wf:
        emit(
            "audio.generated",
            wav=str(wav_path),
            pcm=str(pcm_path),
            frames=wf.getnframes(),
            rate=wf.getframerate(),
            channels=wf.getnchannels(),
            duration_s=round(wf.getnframes() / wf.getframerate(), 3),
        )


async def sync_transcribe(api_key: str, wav_path: Path, expected: str) -> dict[str, Any]:
    models = ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"]
    async with httpx.AsyncClient(timeout=60) as client:
        last_error = None
        for model in models:
            emit("sync_transcribe.start", model=model)
            with wav_path.open("rb") as f:
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    data={"model": model, "language": "en"},
                    files={"file": (wav_path.name, f, "audio/wav")},
                )
            if response.status_code >= 400:
                last_error = {"model": model, "status": response.status_code, "body": response.text[:500]}
                emit("sync_transcribe.error", **last_error)
                continue
            payload = response.json()
            transcript = payload.get("text", "")
            score = match_score(expected, transcript)
            result = {"model": model, "status": response.status_code, "transcript": transcript, "score": score}
            emit("sync_transcribe.done", **result)
            return result
    raise RuntimeError(f"all sync transcription models failed: {last_error}")


async def websocket_connect(url: str, headers: dict[str, str]):
    try:
        return await websockets.connect(url, additional_headers=headers, ping_interval=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, ping_interval=None)


async def realtime_transcribe(api_key: str, pcm_path: Path, expected: str, delay: str = "low") -> dict[str, Any]:
    url_candidates = [
        "wss://api.openai.com/v1/realtime?intent=transcription",
    ]
    headers = {
        "Authorization": f"Bearer {api_key}",
    }
    audio = pcm_path.read_bytes()
    chunks = [audio[i:i + 4800] for i in range(0, len(audio), 4800)]  # 100ms @ 24kHz s16 mono
    last_error = None
    for url in url_candidates:
        emit("realtime_transcribe.connect", url=url.replace(api_key, "[REDACTED]"), chunks=len(chunks))
        try:
            async with await websocket_connect(url, headers) as ws:
                await ws.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        "type": "transcription",
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "transcription": {"model": "gpt-realtime-whisper", "language": "en", "delay": delay},
                                "turn_detection": None,
                            }
                        }
                    },
                }))
                saw = []
                final_transcript = ""
                # consume session.created/updated opportunistically while streaming chunks
                for idx, chunk in enumerate(chunks):
                    await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(chunk).decode("ascii")}))
                    if idx % 5 == 0:
                        await asyncio.sleep(0.01)
                await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3)
                    except asyncio.TimeoutError:
                        continue
                    event = json.loads(raw)
                    etype = event.get("type")
                    saw.append(etype)
                    if etype in {"error", "session.updated", "input_audio_buffer.committed", "conversation.item.input_audio_transcription.completed"}:
                        emit("realtime_transcribe.event", type=etype, error=event.get("error"), transcript=event.get("transcript"))
                    if etype == "error":
                        last_error = event.get("error") or event
                        break
                    if etype == "conversation.item.input_audio_transcription.completed":
                        final_transcript = event.get("transcript", "")
                        break
                if final_transcript:
                    score = match_score(expected, final_transcript)
                    result = {"status": "ok", "transcript": final_transcript, "score": score, "events_seen": saw[-20:]}
                    emit("realtime_transcribe.done", **result)
                    return result
                last_error = {"message": "no final transcript", "events_seen": saw[-20:]}
                emit("realtime_transcribe.no_final", **last_error)
        except Exception as exc:
            last_error = {"type": type(exc).__name__, "message": str(exc)[:500]}
            emit("realtime_transcribe.exception", **last_error)
    raise RuntimeError(f"realtime transcription failed: {last_error}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--artifact-dir", type=Path, default=ARTIFACT_DIR / time.strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()

    load_env_file(Path.home() / ".config" / "hermes-tailchat.env")
    load_env_file(Path.home() / ".hermes" / ".env")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing")

    wav_path = args.artifact_dir / "probe.wav"
    pcm_path = args.artifact_dir / "probe.pcm"
    generate_audio(args.text, wav_path, pcm_path)
    sync_result = await sync_transcribe(api_key, wav_path, args.text)
    realtime_result = await realtime_transcribe(api_key, pcm_path, args.text)
    passed = bool(sync_result["score"]["pass"] and realtime_result["score"]["pass"])
    summary = {
        "passed": passed,
        "expected": args.text,
        "artifact_dir": str(args.artifact_dir),
        "sync": sync_result,
        "realtime_async": realtime_result,
    }
    (args.artifact_dir / "summary.json").write_text(json.dumps(redact(summary), indent=2, ensure_ascii=False))
    emit("summary", **summary)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
