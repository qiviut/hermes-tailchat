#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')


def append_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(text)
        if not text.endswith('\n'):
            handle.write('\n')


def run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True)
    if check and completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f'command failed: {command!r}')
    return completed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run a Codex background task with optional Agent Mail coordination.')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--artifacts', required=True)
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--task', default='background codex task')
    parser.add_argument('--thread-id')
    parser.add_argument('--bead-id')
    parser.add_argument('--model', default='gpt-5')
    parser.add_argument('--reservation-reason')
    parser.add_argument('--reserve', action='append', default=[])
    parser.add_argument('--notify-to', action='append', default=[])
    parser.add_argument('--agent-name')
    parser.add_argument('--agent-mail', choices=['optional', 'required', 'off'], default='optional')
    return parser.parse_args()


def bootstrap_agent_mail(args: argparse.Namespace, repo: Path, artifacts: Path, status: dict[str, Any]) -> dict[str, Any]:
    if args.agent_mail == 'off':
        return {}
    if shutil.which('am') is None:
        if args.agent_mail == 'required':
            raise RuntimeError('Agent Mail CLI `am` is not available on PATH')
        status.setdefault('warnings', []).append('Agent Mail CLI `am` not available; continuing without coordination bootstrap')
        return {}

    command = [
        'am', 'macros', 'start-session', '--json',
        '--project', str(repo),
        '--program', 'codex-cli',
        '--model', args.model,
        '--task', args.task,
    ]
    if args.agent_name:
        command.extend(['--agent-name', args.agent_name])
    if args.reservation_reason:
        command.extend(['--reserve-reason', args.reservation_reason])
    if args.reserve:
        for reserved in args.reserve:
            command.extend(['--reserve', reserved])

    try:
        completed = run_command(command)
    except Exception as exc:
        if args.agent_mail == 'required':
            raise
        status.setdefault('warnings', []).append(f'Agent Mail bootstrap failed: {exc}')
        return {}

    append_log(artifacts / 'agent-mail.log', completed.stdout)
    payload = json.loads(completed.stdout)
    write_json(artifacts / 'agent-mail-bootstrap.json', payload)
    return payload


def maybe_send_mail(repo: Path, artifacts: Path, sender: str, recipients: list[str], subject: str, body: str, thread_id: str | None) -> None:
    if not recipients:
        return
    command = [
        'am', 'mail', 'send', '--json',
        '--project', str(repo),
        '--from', sender,
        '--to', ','.join(recipients),
        '--subject', subject,
        '--body', body,
    ]
    if thread_id:
        command.extend(['--thread-id', thread_id])
    completed = run_command(command, check=False)
    append_log(artifacts / 'agent-mail.log', completed.stdout or completed.stderr)


def release_reservations(repo: Path, artifacts: Path, agent_name: str | None) -> None:
    if not agent_name or shutil.which('am') is None:
        return
    completed = run_command(['am', 'file_reservations', 'release', str(repo), agent_name], check=False)
    append_log(artifacts / 'agent-mail.log', completed.stdout or completed.stderr)


def build_prompt(args: argparse.Namespace, agent_name: str | None) -> str:
    constraints = [
        'You are a Codex worker launched by Hermes Tailchat for background work.',
        'Stay inside the current repository checkout.',
        'Return a concise operator-facing final summary with: what changed, tests/commands run, and any follow-up risks.',
    ]
    if agent_name:
        constraints.append(f'Your Agent Mail identity for this task is `{agent_name}`.')
    if args.thread_id:
        constraints.append(f'Use thread `{args.thread_id}` as the coordination anchor in any notes or summaries.')
    if args.bead_id:
        constraints.append(f'This task is associated with bead `{args.bead_id}`.')
    if args.reserve:
        constraints.append('Reserved paths for this task: ' + ', '.join(args.reserve))
    constraints.append('If you make edits, respect repo conventions and leave the working tree understandable for review.')
    return '\n'.join(f'- {item}' for item in constraints) + f"\n\nTask:\n{args.prompt}\n"


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    artifacts = Path(args.artifacts).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    status: dict[str, Any] = {
        'state': 'launching',
        'repo': str(repo),
        'artifacts': str(artifacts),
        'thread_id': args.thread_id,
        'bead_id': args.bead_id,
        'reserve_paths': args.reserve,
        'notify_to': args.notify_to,
        'started_at': iso_now(),
        'model': args.model,
        'warnings': [],
    }
    write_json(artifacts / 'status.json', status)

    bootstrap = {}
    agent_name = args.agent_name
    try:
        bootstrap = bootstrap_agent_mail(args, repo, artifacts, status)
        if bootstrap.get('agent', {}).get('name'):
            agent_name = bootstrap['agent']['name']
        status['agent_mail'] = {
            'enabled': bool(bootstrap),
            'agent_name': agent_name,
            'project': bootstrap.get('project', {}).get('human_key'),
        }
        write_json(artifacts / 'status.json', status)

        maybe_send_mail(
            repo,
            artifacts,
            agent_name or 'tailchat-codex',
            args.notify_to,
            f'[{args.thread_id or args.bead_id or "tailchat"}] Codex task started',
            f'Background Codex task started.\n\nTask: {args.task}\nArtifacts: {artifacts}',
            args.thread_id,
        )

        prompt = build_prompt(args, agent_name)
        (artifacts / 'prompt.txt').write_text(prompt)
        status['state'] = 'running'
        status['codex_command'] = [
            'codex', 'exec', '--json', '--full-auto', '--output-last-message', str(artifacts / 'final.md'), prompt,
        ]
        write_json(artifacts / 'status.json', status)

        with (artifacts / 'events.jsonl').open('w', encoding='utf-8') as events_handle, (artifacts / 'stderr.log').open('w', encoding='utf-8') as stderr_handle:
            completed = subprocess.run(
                ['codex', 'exec', '--json', '--full-auto', '--output-last-message', str(artifacts / 'final.md'), prompt],
                cwd=repo,
                stdout=events_handle,
                stderr=stderr_handle,
                text=True,
            )

        status['finished_at'] = iso_now()
        status['returncode'] = completed.returncode
        if completed.returncode == 0:
            status['state'] = 'completed'
            maybe_send_mail(
                repo,
                artifacts,
                agent_name or 'tailchat-codex',
                args.notify_to,
                f'[{args.thread_id or args.bead_id or "tailchat"}] Codex task completed',
                f'Background Codex task completed successfully.\n\nArtifacts: {artifacts}',
                args.thread_id,
            )
            write_json(artifacts / 'status.json', status)
            return 0

        error_text = (artifacts / 'stderr.log').read_text().strip()
        status['state'] = 'error'
        status['error'] = error_text or 'codex exec failed'
        maybe_send_mail(
            repo,
            artifacts,
            agent_name or 'tailchat-codex',
            args.notify_to,
            f'[{args.thread_id or args.bead_id or "tailchat"}] Codex task failed',
            f'Background Codex task failed.\n\nArtifacts: {artifacts}\nError: {status["error"]}',
            args.thread_id,
        )
        write_json(artifacts / 'status.json', status)
        return completed.returncode or 1
    except Exception as exc:
        status['finished_at'] = iso_now()
        status['state'] = 'error'
        status['error'] = str(exc)
        write_json(artifacts / 'status.json', status)
        return 1
    finally:
        release_reservations(repo, artifacts, agent_name)


if __name__ == '__main__':
    sys.exit(main())
