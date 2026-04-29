from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

_SAFE_REF_RE = re.compile(r"[^A-Za-z0-9_.@:-]+")


def content_hash(payload: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 hash for a JSON-like payload."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    import hashlib

    return hashlib.sha256(encoded).hexdigest()


def safe_ref(source_ref: str) -> str:
    cleaned = _SAFE_REF_RE.sub("-", source_ref.strip()).strip(".-")
    return cleaned[:160] or "unknown"


def spool_path(root: str | Path, stage: str, source_type: str, source_ref: str, payload: Mapping[str, Any]) -> Path:
    digest = content_hash(payload)[:16]
    return Path(root) / stage / source_type / f"{safe_ref(source_ref)}-{digest}.json"


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, target)
    return target


def spool_json(root: str | Path, stage: str, source_type: str, source_ref: str, payload: Mapping[str, Any]) -> Path:
    return write_json_atomic(spool_path(root, stage, source_type, source_ref, payload), payload)
