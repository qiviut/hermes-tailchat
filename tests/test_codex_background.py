from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

import asyncio
import pytest

from tests.test_smoke import load_app
from app.codex_runner import (
    CodexRunnerError,
    _can_retry_codex_attempt,
    _is_transient_codex_error,
    run_codex_task,
)


def make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_codex_background_script_writes_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()
    artifacts = tmp_path / 'artifacts'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    mail_log = tmp_path / 'mail.log'

    make_executable(
        bin_dir / 'am',
        f"""#!/usr/bin/env python3
import json, pathlib, sys
pathlib.Path({str(mail_log)!r}).write_text(pathlib.Path({str(mail_log)!r}).read_text() + ' '.join(sys.argv[1:]) + '\\n' if pathlib.Path({str(mail_log)!r}).exists() else ' '.join(sys.argv[1:]) + '\\n')
if sys.argv[1:3] == ['macros', 'start-session']:
    print(json.dumps({{
        'project': {{'human_key': sys.argv[sys.argv.index('--project') + 1]}},
        'agent': {{'name': 'BronzeSalmon'}},
        'file_reservations': {{'granted': [], 'conflicts': []}},
        'inbox': [],
    }}))
elif sys.argv[1:3] == ['mail', 'send']:
    print(json.dumps({{'ok': True}}))
elif sys.argv[1:3] == ['file_reservations', 'release']:
    print('released')
else:
    print(json.dumps({{'ok': True}}))
""",
    )
    make_executable(
        bin_dir / 'codex',
        """#!/usr/bin/env python3
import json, pathlib, sys
final_path = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
final_path.write_text('codex final summary\\n')
print(json.dumps({'type': 'thread.started'}))
print(json.dumps({'type': 'turn.completed'}))
""",
    )

    env = os.environ | {'PATH': f"{bin_dir}:{os.environ['PATH']}"}
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'run_codex_background.py'
    result = os.spawnve(
        os.P_WAIT,
        sys.executable,
        [sys.executable, str(script), '--repo', str(repo), '--artifacts', str(artifacts), '--prompt', 'Inspect this repo', '--task', 'Inspect this repo', '--thread-id', 'thread-123', '--notify-to', 'BlueLake'],
        env,
    )

    assert result == 0
    status = json.loads((artifacts / 'status.json').read_text())
    assert status['state'] == 'completed'
    assert status['agent_mail']['agent_name'] == 'BronzeSalmon'
    assert (artifacts / 'final.md').read_text().strip() == 'codex final summary'
    assert 'thread.started' in (artifacts / 'events.jsonl').read_text()
    assert 'mail send' in mail_log.read_text()


def test_codex_job_runs_through_background_poller_with_fake_script(tmp_path: Path) -> None:
    fake_script = tmp_path / 'fake_codex_script.py'
    fake_script.write_text(
        """#!/usr/bin/env python3
import json, sys
from pathlib import Path
artifacts = Path(sys.argv[sys.argv.index('--artifacts') + 1])
artifacts.mkdir(parents=True, exist_ok=True)
(artifacts / 'final.md').write_text('background codex result\\n')
(artifacts / 'status.json').write_text(json.dumps({'state': 'completed', 'artifact_dir': str(artifacts)}))
"""
    )
    fake_script.chmod(fake_script.stat().st_mode | stat.S_IXUSR)

    os.environ['TAILCHAT_CODEX_BACKGROUND_SCRIPT'] = str(fake_script)
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        created = client.post('/api/conversations', json={'title': 'codex background'})
        convo = created.json()
        queued = client.post(
            f"/api/conversations/{convo['id']}/jobs",
            json={
                'prompt': 'Review the repo for risky areas',
                'delay_seconds': 0,
                'executor': 'codex',
                'thread_id': 'hermes-tailchat-ood',
                'reserve_paths': ['app/*.py'],
            },
        )
        assert queued.status_code == 200
        job = queued.json()
        assert job['executor'] == 'codex'
        assert job['metadata']['thread_id'] == 'hermes-tailchat-ood'

        deadline = time.time() + 6
        latest_job = job
        while time.time() < deadline:
            latest_job = client.get(f"/api/conversations/{convo['id']}/jobs").json()[0]
            if latest_job['status'] == 'complete':
                break
            time.sleep(0.25)

        assert latest_job['status'] == 'complete'
        assert latest_job['artifact_dir']
        messages = client.get(f"/api/conversations/{convo['id']}/messages").json()
        assert any(msg['content'] == 'background codex result' for msg in messages)


def test_transient_codex_error_helpers_detect_safe_retry_conditions() -> None:
    assert _is_transient_codex_error('429 rate limit; retry after 3s')
    assert not _can_retry_codex_attempt({
        'status': {'error': '429 rate limit; retry after 3s'},
        'stderr': '',
        'stdout': '',
        'final_output': '',
        'events_output': '',
    })
    assert _can_retry_codex_attempt({
        'status': {'error': '503 service unavailable; retry after 3s'},
        'stderr': '',
        'stdout': '',
        'final_output': '',
        'events_output': '',
    })
    assert not _can_retry_codex_attempt({
        'status': {'error': '503 service unavailable; retry after 3s'},
        'stderr': '',
        'stdout': '',
        'final_output': 'partial summary',
        'events_output': '',
    })
    assert not _can_retry_codex_attempt({
        'status': {'error': '503 service unavailable; retry after 3s'},
        'stderr': '',
        'stdout': '',
        'final_output': '',
        'events_output': '{"type":"thread.started"}\n',
    })


def test_run_codex_task_retries_transient_failure_before_any_output(tmp_path: Path, monkeypatch) -> None:
    async def fake_sleep(_seconds: float) -> None:
        return None

    state_file = tmp_path / 'attempt-state.txt'
    fake_script = tmp_path / 'fake_codex_retry.py'
    fake_script.write_text(
        """#!/usr/bin/env python3
import json, sys
from pathlib import Path
state_file = Path(sys.argv[sys.argv.index('--repo') + 1]).parent / 'attempt-state.txt'
artifacts = Path(sys.argv[sys.argv.index('--artifacts') + 1])
artifacts.mkdir(parents=True, exist_ok=True)
attempt = int(state_file.read_text()) + 1 if state_file.exists() else 1
state_file.write_text(str(attempt))
if attempt == 1:
    (artifacts / 'status.json').write_text(json.dumps({'state': 'error', 'error': '503 service unavailable; retry after 1s'}))
    sys.exit(1)
(artifacts / 'final.md').write_text('codex retry success\\n')
(artifacts / 'status.json').write_text(json.dumps({'state': 'completed', 'artifact_dir': str(artifacts)}))
"""
    )
    fake_script.chmod(fake_script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv('TAILCHAT_CODEX_BACKGROUND_SCRIPT', str(fake_script))
    monkeypatch.setenv('TAILCHAT_CODEX_ARTIFACTS_DIR', str(tmp_path / 'artifacts-root'))
    monkeypatch.setenv('HERMES_TAILCHAT_REPO', str(tmp_path / 'repo'))
    monkeypatch.setenv('TAILCHAT_CODEX_TRANSIENT_RETRY_ATTEMPTS', '2')
    monkeypatch.setattr('app.codex_runner.asyncio.sleep', fake_sleep)
    (tmp_path / 'repo').mkdir()

    result = asyncio.run(run_codex_task(job_id='job-retry', prompt='retry please'))

    assert result['attempt'] == 2
    assert result['final_output'] == 'codex retry success'
    assert state_file.read_text() == '2'


def test_run_codex_task_refuses_retry_after_events_exist(tmp_path: Path, monkeypatch) -> None:
    async def fake_sleep(_seconds: float) -> None:
        return None

    fake_script = tmp_path / 'fake_codex_events_then_fail.py'
    fake_script.write_text(
        """#!/usr/bin/env python3
import json, sys
from pathlib import Path
artifacts = Path(sys.argv[sys.argv.index('--artifacts') + 1])
artifacts.mkdir(parents=True, exist_ok=True)
(artifacts / 'events.jsonl').write_text('{\"type\":\"thread.started\"}\\n')
(artifacts / 'status.json').write_text(json.dumps({'state': 'error', 'error': '503 service unavailable after event'}))
sys.exit(1)
"""
    )
    fake_script.chmod(fake_script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv('TAILCHAT_CODEX_BACKGROUND_SCRIPT', str(fake_script))
    monkeypatch.setenv('TAILCHAT_CODEX_ARTIFACTS_DIR', str(tmp_path / 'artifacts-root'))
    monkeypatch.setenv('HERMES_TAILCHAT_REPO', str(tmp_path / 'repo'))
    monkeypatch.setenv('TAILCHAT_CODEX_TRANSIENT_RETRY_ATTEMPTS', '3')
    monkeypatch.setattr('app.codex_runner.asyncio.sleep', fake_sleep)
    (tmp_path / 'repo').mkdir()

    with pytest.raises(CodexRunnerError, match='Transient Codex/OpenAI provider error after 1 attempt'):
        asyncio.run(run_codex_task(job_id='job-events-fail', prompt='do not retry'))


def test_run_codex_task_does_not_retry_429_without_output(tmp_path: Path, monkeypatch) -> None:
    async def fake_sleep(_seconds: float) -> None:
        return None

    state_file = tmp_path / 'attempt-state.txt'
    fake_script = tmp_path / 'fake_codex_rate_limit.py'
    fake_script.write_text(
        """#!/usr/bin/env python3
import json, sys
from pathlib import Path
state_file = Path(sys.argv[sys.argv.index('--repo') + 1]).parent / 'attempt-state.txt'
artifacts = Path(sys.argv[sys.argv.index('--artifacts') + 1])
artifacts.mkdir(parents=True, exist_ok=True)
attempt = int(state_file.read_text()) + 1 if state_file.exists() else 1
state_file.write_text(str(attempt))
(artifacts / 'status.json').write_text(json.dumps({'state': 'error', 'error': '429 rate limit; retry after 30s'}))
sys.exit(1)
"""
    )
    fake_script.chmod(fake_script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv('TAILCHAT_CODEX_BACKGROUND_SCRIPT', str(fake_script))
    monkeypatch.setenv('TAILCHAT_CODEX_ARTIFACTS_DIR', str(tmp_path / 'artifacts-root'))
    monkeypatch.setenv('HERMES_TAILCHAT_REPO', str(tmp_path / 'repo'))
    monkeypatch.setenv('TAILCHAT_CODEX_TRANSIENT_RETRY_ATTEMPTS', '3')
    monkeypatch.setattr('app.codex_runner.asyncio.sleep', fake_sleep)
    (tmp_path / 'repo').mkdir()

    with pytest.raises(CodexRunnerError, match='Transient Codex/OpenAI provider error after 1 attempt'):
        asyncio.run(run_codex_task(job_id='job-rate-limit', prompt='do not retry 429'))

    assert state_file.read_text() == '1'
