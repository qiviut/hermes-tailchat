from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


class CodexRunnerError(RuntimeError):
    pass


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

    result = {
        'artifact_dir': str(artifacts_dir),
        'status': status,
        'final_output': final_output,
        'stdout': stdout.decode(),
        'stderr': stderr.decode(),
        'returncode': proc.returncode,
        'command': command,
    }
    if proc.returncode != 0:
        error = status.get('error') or result['stderr'] or result['stdout'] or 'codex background task failed'
        raise CodexRunnerError(error)
    return result
