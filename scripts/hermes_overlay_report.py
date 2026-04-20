#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.overlay import build_overlay_report



def main() -> int:
    parser = argparse.ArgumentParser(description='Export a deterministic report for a local Hermes overlay git checkout.')
    parser.add_argument('repo', nargs='?', default=str(Path.home() / '.hermes' / 'hermes-agent'))
    parser.add_argument('--export-dir', default=str(Path.home() / '.local' / 'state' / 'hermes-tailchat' / 'dreaming' / 'overlay'))
    args = parser.parse_args()

    report = build_overlay_report(Path(args.repo).expanduser(), export_dir=Path(args.export_dir).expanduser())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
