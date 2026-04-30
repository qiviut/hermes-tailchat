#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.swyx_ingest.extract import spool_raw_item, spool_reduced_item
from app.swyx_ingest.sources import fetch_x_query, load_manual_json, parse_xurl_items


def _summarize_item(item: Any) -> dict[str, Any]:
    return {"source_type": item.source_type, "source_ref": item.source_ref, "source_url": item.source_url}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest swyx source items into a deterministic review spool.")
    parser.add_argument("--spool-root", default="data/swyx", help="Directory for raw/normalized/candidate artifacts")
    parser.add_argument("--manual-json", help="Local JSON file with SourceItem-like objects")
    parser.add_argument("--x-query", help="Bounded xurl search query, e.g. 'from:swyx'")
    parser.add_argument("--x-limit", type=int, default=10, help="xurl result limit, 1-100")
    parser.add_argument("--reduce", action="store_true", help="Also write normalized untrusted-ingest artifacts")
    parser.add_argument("--dry-run", action="store_true", help="Parse/fetch and summarize without writing files")
    args = parser.parse_args(argv)
    if args.x_limit < 1 or args.x_limit > 100:
        parser.error("--x-limit must be between 1 and 100")

    items = []
    if args.manual_json:
        items.extend(load_manual_json(args.manual_json))
    if args.x_query:
        payload = fetch_x_query(args.x_query, limit=args.x_limit)
        items.extend(parse_xurl_items(payload, query=args.x_query))
    if not items:
        parser.error("provide --manual-json or --x-query")

    raw_paths: list[str] = []
    normalized_paths: list[str] = []
    if not args.dry_run:
        for item in items:
            raw_paths.append(str(spool_raw_item(args.spool_root, item)))
            if args.reduce:
                _, path = spool_reduced_item(args.spool_root, item)
                normalized_paths.append(str(path))

    print(json.dumps({
        "items": [_summarize_item(item) for item in items],
        "raw_paths": raw_paths,
        "normalized_paths": normalized_paths,
        "dry_run": args.dry_run,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
