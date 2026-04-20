#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.dreaming import build_analysis_candidates, build_dream_report, build_retrieval_index, extract_reflection_windows, filter_recent_sessions
from app.overlay import build_overlay_report


DEFAULT_STATE_DIR = Path.home() / '.local' / 'state' / 'hermes-tailchat' / 'dreaming'
DEFAULT_OVERLAY_REPO = Path.home() / '.hermes' / 'hermes-agent'
DEFAULT_HERMES_BIN = Path(os.getenv('HERMES_BIN', str(Path.home() / '.local' / 'bin' / 'hermes')))
DEFAULT_CONTEXT_FILES = [
    ROOT_DIR / 'AGENTS.md',
    ROOT_DIR / 'README.md',
    ROOT_DIR / 'docs' / 'design' / '2026-04-18-hermes-dreaming-toolkit.md',
    ROOT_DIR / 'docs' / 'design' / '2026-04-19-hermes-memory-hierarchy-and-frame-of-mind-retrieval.md',
]



def export_sessions(hermes_bin: Path) -> list[dict]:
    with tempfile.NamedTemporaryFile(prefix='hermes-sessions-', suffix='.jsonl', delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        subprocess.run([str(hermes_bin), 'sessions', 'export', str(temp_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sessions = []
        with temp_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                sessions.append(json.loads(line))
        return sessions
    finally:
        temp_path.unlink(missing_ok=True)



def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None



def main() -> int:
    parser = argparse.ArgumentParser(description='Collect deterministic Hermes dreaming telemetry.')
    parser.add_argument('--state-dir', default=str(DEFAULT_STATE_DIR))
    parser.add_argument('--lookback-hours', type=int, default=24)
    parser.add_argument('--max-idle-minutes', type=int, default=65)
    parser.add_argument('--overlay-repo', default=str(DEFAULT_OVERLAY_REPO))
    parser.add_argument('--hermes-bin', default=str(DEFAULT_HERMES_BIN))
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    previous_report = _load_json(state_dir / 'latest-summary.json')

    sessions = export_sessions(Path(args.hermes_bin).expanduser())
    now_ts = time.time()

    overlay_export_dir = state_dir / 'overlay'
    overlay = build_overlay_report(Path(args.overlay_repo).expanduser(), export_dir=overlay_export_dir)
    report = build_dream_report(
        sessions,
        now_ts=now_ts,
        lookback_seconds=args.lookback_hours * 3600,
        max_idle_seconds=args.max_idle_minutes * 60,
        state_dir=state_dir,
        overlay=overlay,
    )
    recent_sessions = filter_recent_sessions(sessions, now_ts=now_ts, lookback_seconds=args.lookback_hours * 3600)
    windows = extract_reflection_windows(recent_sessions) if report['status'] == 'ready' else []
    analysis = build_analysis_candidates(report, windows, previous_report=previous_report)
    retrieval = build_retrieval_index(
        report,
        windows,
        analysis,
        context_files=[str(path) for path in DEFAULT_CONTEXT_FILES if path.exists()],
        log_files=[str(state_dir / 'runs.jsonl')],
    )

    (state_dir / 'latest-summary.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    (state_dir / 'windows.json').write_text(json.dumps(windows, indent=2, sort_keys=True) + '\n')
    (state_dir / 'analysis-candidates.json').write_text(json.dumps(analysis, indent=2, sort_keys=True) + '\n')
    (state_dir / 'retrieval-index.json').write_text(json.dumps(retrieval, indent=2, sort_keys=True) + '\n')
    (state_dir / 'overlay-report.json').write_text(json.dumps(overlay, indent=2, sort_keys=True) + '\n')
    with (state_dir / 'runs.jsonl').open('a') as handle:
        handle.write(
            json.dumps(
                {
                    'report': report,
                    'analysis': {
                        'summary': analysis.get('summary'),
                        'deltas': analysis.get('deltas'),
                    },
                    'window_count': len(windows),
                },
                sort_keys=True,
            )
            + '\n'
        )

    print(
        json.dumps(
            {
                'status': report['status'],
                'latest_summary': str(state_dir / 'latest-summary.json'),
                'analysis_candidates': str(state_dir / 'analysis-candidates.json'),
                'retrieval_index': str(state_dir / 'retrieval-index.json'),
                'overlay_report': str(state_dir / 'overlay-report.json'),
                'windows': len(windows),
            }
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
