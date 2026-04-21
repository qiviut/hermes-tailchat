#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.untrusted_ingest import available_pipelines, inspect_git_revision, inspect_payload, inspect_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic untrusted-ingestion reducer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    text_parser = subparsers.add_parser("text", help="Inspect text from stdin or a file")
    text_parser.add_argument("--source-type", required=True, choices=available_pipelines())
    text_parser.add_argument("--source-ref", required=True)
    text_parser.add_argument("--file", type=Path)

    json_parser = subparsers.add_parser("json", help="Inspect JSON from stdin or a file")
    json_parser.add_argument("--source-type", required=True, choices=available_pipelines())
    json_parser.add_argument("--source-ref", required=True)
    json_parser.add_argument("--file", type=Path)

    git_parser = subparsers.add_parser("git", help="Inspect a git revision")
    git_parser.add_argument("--repo", type=Path, default=Path("."))
    git_parser.add_argument("--revision", default="HEAD")

    return parser


def _read_text(path: Path | None) -> str:
    if path:
        return path.read_text()
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "text":
        text = _read_text(args.file)
        artifact = inspect_text(text, source_type=args.source_type, source_ref=args.source_ref)
    elif args.command == "json":
        payload = json.loads(_read_text(args.file))
        artifact = inspect_payload(payload, source_type=args.source_type, source_ref=args.source_ref)
    else:
        artifact = inspect_git_revision(args.repo, args.revision)

    json.dump(artifact, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
