from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from .retry_policy import can_auto_retry_error, is_transient_error, parse_retry_after_seconds


class CodexRunnerError(RuntimeError):
    pass


def _is_transient_codex_error(error_text: str | None) -> bool:
    return is_transient_error(error_text)


def _parse_retry_after_seconds(error_text: str | None) -> int | None:
    return parse_retry_after_seconds(error_text)


def _can_retry_codex_attempt(result: dict[str, Any]) -> bool:
    if (result.get('final_output') or '').strip():
        return False
    if (result.get('events_output') or '').strip():
        return False
    error_text = result.get('status', {}).get('error') or result.get('stderr') or result.get('stdout')
    return can_auto_retry_error(error_text)


def repo_root() -> Path:
    return Path(os.getenv('HERMES_TAILCHAT_REPO', Path(__file__).resolve().parent.parent)).resolve()


def artifacts_root() -> Path:
    root = Path(os.getenv('TAILCHAT_CODEX_ARTIFACTS_DIR', repo_root() / '.tailchat' / 'codex-jobs'))
    root.mkdir(parents=True, exist_ok=True)
    return root


def script_path() -> Path:
    return Path(os.getenv('TAILCHAT_CODEX_BACKGROUND_SCRIPT', repo_root() / 'scripts' / 'run_codex_background.py')).resolve()


def job_artifacts_dir(job_id: str) -> Path:
    return artifacts_root() / job_id


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


async def run_codex_task(
    *,
    job_id: str,
    prompt: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    artifacts_dir = job_artifacts_dir(job_id)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    max_attempts = max(1, int(os.getenv('TAILCHAT_CODEX_TRANSIENT_RETRY_ATTEMPTS', '2')))

    command = [
        sys.executable,
        str(script_path()),
        '--repo',
        str(repo_root()),
        '--artifacts',
        str(artifacts_dir),
        '--prompt',
        prompt,
        '--task',
        metadata.get('task') or prompt,
        '--agent-mail',
        metadata.get('agent_mail_mode') or 'optional',
    ]

    thread_id = metadata.get('thread_id') or f'hermes-tailchat-job-{job_id}'
    if thread_id:
        command.extend(['--thread-id', thread_id])

    reservation_reason = metadata.get('reservation_reason') or metadata.get('bead_id') or thread_id
    if reservation_reason:
        command.extend(['--reservation-reason', reservation_reason])

    for path in metadata.get('reserve_paths', []):
        command.extend(['--reserve', path])

    for recipient in metadata.get('notify_to', []):
        command.extend(['--notify-to', recipient])

    bead_id = metadata.get('bead_id')
    if bead_id:
        command.extend(['--bead-id', bead_id])

    model = metadata.get('model')
    if model:
        command.extend(['--model', model])

    for attempt in range(1, max_attempts + 1):
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        status = _load_json(artifacts_dir / 'status.json')
        final_output = ''
        final_path = artifacts_dir / 'final.md'
        if final_path.exists():
            final_output = final_path.read_text().strip()
        events_output = ''
        events_path = artifacts_dir / 'events.jsonl'
        if events_path.exists():
            events_output = events_path.read_text()

        result = {
            'artifact_dir': str(artifacts_dir),
            'status': status,
            'final_output': final_output,
            'events_output': events_output,
            'stdout': stdout.decode(),
            'stderr': stderr.decode(),
            'returncode': proc.returncode,
            'command': command,
            'attempt': attempt,
            'max_attempts': max_attempts,
        }
        if proc.returncode == 0:
            return result

        if attempt < max_attempts and _can_retry_codex_attempt(result):
            retry_after = _parse_retry_after_seconds(result['status'].get('error') or result['stderr'] or result['stdout'])
            await asyncio.sleep(retry_after or min(20, 2 ** (attempt - 1)))
            continue

        error = status.get('error') or result['stderr'] or result['stdout'] or 'codex background task failed'
        if _is_transient_codex_error(error):
            raise CodexRunnerError(
                f'Transient Codex/OpenAI provider error after {attempt} attempt(s): {error}\n\n'
                'Tailchat only auto-retries Codex jobs before any task output or events are produced, to avoid duplicating repo side effects.'
            )
        raise CodexRunnerError(error)
