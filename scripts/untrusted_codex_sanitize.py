#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.codex_sanitizer import DEFAULT_MODEL, run_codex_sanitizer
from app.untrusted_ingest import inspect_git_revision, inspect_payload, inspect_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Run isolated Codex sanitization for untrusted input artifacts')
    parser.add_argument('--model', default=DEFAULT_MODEL, help='Codex model to use for the sanitizer pass')

    subparsers = parser.add_subparsers(dest='command', required=True)

    artifact_parser = subparsers.add_parser('artifact', help='Sanitize a prebuilt normalized artifact JSON file')
    artifact_parser.add_argument('--file', type=Path, required=True)

    text_parser = subparsers.add_parser('text', help='Inspect raw text and then sanitize it with Codex')
    text_parser.add_argument('--source-type', required=True)
    text_parser.add_argument('--source-ref', required=True)
    text_parser.add_argument('--file', type=Path)

    json_parser = subparsers.add_parser('json', help='Inspect JSON payload and then sanitize it with Codex')
    json_parser.add_argument('--source-type', required=True)
    json_parser.add_argument('--source-ref', required=True)
    json_parser.add_argument('--file', type=Path)

    git_parser = subparsers.add_parser('git', help='Inspect a git revision and then sanitize it with Codex')
    git_parser.add_argument('--repo', type=Path, default=Path('.'))
    git_parser.add_argument('--revision', default='HEAD')

    return parser


def _read_text(path: Path | None) -> str:
    if path:
        return path.read_text(encoding='utf-8')
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == 'artifact':
        artifact = json.loads(args.file.read_text(encoding='utf-8'))
    elif args.command == 'text':
        artifact = inspect_text(_read_text(args.file), source_type=args.source_type, source_ref=args.source_ref)
    elif args.command == 'json':
        artifact = inspect_payload(json.loads(_read_text(args.file)), source_type=args.source_type, source_ref=args.source_ref)
    else:
        artifact = inspect_git_revision(args.repo, args.revision)

    sanitized = run_codex_sanitizer(artifact, model=args.model)
    payload = {
        'artifact': artifact,
        'sanitized': sanitized,
        'sanitizer_model': args.model,
    }
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
