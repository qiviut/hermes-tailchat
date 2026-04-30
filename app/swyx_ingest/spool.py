from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

_SAFE_REF_RE = re.compile(r"[^A-Za-z0-9_.@:-]+")
_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_VOLATILE_HASH_KEYS = {"fetched_at"}


def _stable_hash_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_hash_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_HASH_KEYS
        }
    if isinstance(value, list):
        return [_stable_hash_payload(item) for item in value]
    return value


def content_hash(payload: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 hash for a JSON-like payload.

    Ingestion timestamps are intentionally excluded so repeated imports of the
    same source record deduplicate to the same deterministic spool path. The
    timestamp remains in the written JSON for provenance.
    """

    encoded = json.dumps(_stable_hash_payload(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    import hashlib

    return hashlib.sha256(encoded).hexdigest()


def safe_ref(source_ref: str) -> str:
    cleaned = _SAFE_REF_RE.sub("-", source_ref.strip()).strip(".-")
    return cleaned[:160] or "unknown"


def safe_segment(value: str) -> str:
    cleaned = _SAFE_SEGMENT_RE.sub("-", str(value).strip()).strip(".-")
    if not cleaned or cleaned in {".", ".."}:
        return "unknown"
    return cleaned[:80]


def spool_path(root: str | Path, stage: str, source_type: str, source_ref: str, payload: Mapping[str, Any]) -> Path:
    digest = content_hash(payload)[:16]
    return Path(root) / safe_segment(stage) / safe_segment(source_type) / f"{safe_ref(source_ref)}-{digest}.json"


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, target)
    return target


def spool_json(root: str | Path, stage: str, source_type: str, source_ref: str, payload: Mapping[str, Any]) -> Path:
    return write_json_atomic(spool_path(root, stage, source_type, source_ref, payload), payload)
