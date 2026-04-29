from __future__ import annotations

from pathlib import Path
from typing import Any

from app.untrusted_ingest import inspect_payload

from .sources import SourceItem
from .spool import spool_json

_SOURCE_MAP = {
    "x": "x",
    "twitter": "x",
    "smol": "web",
    "smol.ai": "web",
    "latent_space": "web",
    "podcast": "web",
    "youtube": "web",
    "web": "web",
}


def reducer_source_type(source_type: str) -> str:
    return _SOURCE_MAP.get(source_type, "web")


def reducer_payload(item: SourceItem) -> dict[str, Any]:
    if reducer_source_type(item.source_type) == "x":
        return {
            "author": item.raw_fields.get("author"),
            "timestamp": item.raw_fields.get("timestamp") or item.raw_fields.get("created_at"),
            "text": item.raw_fields.get("text", ""),
            "urls": item.raw_fields.get("urls", []),
            "conversation_id": item.raw_fields.get("conversation_id"),
            "media": item.raw_fields.get("media", []),
        }
    return {
        "url": item.source_url or item.raw_fields.get("url"),
        "title": item.raw_fields.get("title"),
        "text": item.raw_fields.get("text") or item.raw_fields.get("description") or item.raw_fields.get("transcript") or "",
        "links": item.raw_fields.get("links") or item.raw_fields.get("urls") or [],
        "content_type": item.raw_fields.get("content_type") or item.source_type,
    }


def reduce_item(item: SourceItem) -> dict[str, Any]:
    artifact = inspect_payload(
        reducer_payload(item),
        source_type=reducer_source_type(item.source_type),
        source_ref=item.source_ref,
        fetched_at=item.fetched_at,
    )
    flags = artifact.setdefault("deterministic_flags", [])
    if "untrusted_input" not in flags:
        flags.append("untrusted_input")
        artifact["deterministic_flags"] = sorted(flags)
    return artifact


def spool_raw_item(root: str | Path, item: SourceItem) -> Path:
    return spool_json(root, "raw", item.source_type, item.source_ref, item.to_json())


def spool_reduced_item(root: str | Path, item: SourceItem) -> tuple[dict[str, Any], Path]:
    artifact = reduce_item(item)
    path = spool_json(root, "normalized", artifact["source_type"], item.source_ref, artifact)
    return artifact, path
