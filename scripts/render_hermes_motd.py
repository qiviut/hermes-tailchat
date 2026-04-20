#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.dreaming import render_motd


DEFAULT_STATE_DIR = Path.home() / '.local' / 'state' / 'hermes-tailchat' / 'dreaming'



def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None



def main() -> int:
    parser = argparse.ArgumentParser(description='Render a compact Hermes MOTD from the latest dream summary.')
    parser.add_argument('--state-dir', default=str(DEFAULT_STATE_DIR))
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    summary_path = state_dir / 'latest-summary.json'
    if not summary_path.exists():
        print('Hermes summary')
        print(f'- no dream summary yet: run {Path(__file__).resolve().parent / "hermes_dream.py"}')
        print(f'- expected summary path: {summary_path}')
        return 0

    report = json.loads(summary_path.read_text())
    analysis = _load_json(state_dir / 'analysis-candidates.json')
    print(render_motd(report, analysis=analysis))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
