from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_smoke import load_app


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
