from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class SourceItem:
    source_type: str
    source_ref: str
    source_url: str | None
    raw_fields: dict[str, Any]
    fetched_at: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_manual_json(path: str | Path, *, fetched_at: str | None = None) -> list[SourceItem]:
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, dict) and "items" in payload:
        payload = payload["items"]
    if not isinstance(payload, list):
        raise ValueError("manual JSON must be a list or an object with an items list")
    return [source_item_from_mapping(item, fetched_at=fetched_at) for item in payload]


def source_item_from_mapping(item: MappingLike, *, fetched_at: str | None = None) -> SourceItem:
    data = dict(item)
    raw_fields = data.get("raw_fields") if isinstance(data.get("raw_fields"), dict) else {}
    if not raw_fields:
        raw_fields = {k: v for k, v in data.items() if k not in {"source_type", "source_ref", "source_url", "fetched_at"}}
    source_type = str(data.get("source_type") or raw_fields.get("source_type") or "web")
    source_ref = str(data.get("source_ref") or raw_fields.get("id") or raw_fields.get("url") or "manual")
    return SourceItem(
        source_type=source_type,
        source_ref=source_ref,
        source_url=data.get("source_url") or raw_fields.get("source_url") or raw_fields.get("url"),
        raw_fields=raw_fields,
        fetched_at=str(data.get("fetched_at") or fetched_at or utc_now()),
    )


def parse_xurl_items(payload: dict[str, Any], *, query: str | None = None, fetched_at: str | None = None) -> list[SourceItem]:
    """Convert xurl JSON from search/read/timeline endpoints into SourceItems.

    Raw tweet text remains inside raw_fields and should go through the reducer
    before privileged consumers see it.
    """

    fetched_at = fetched_at or utc_now()
    data = payload.get("data")
    if data is None:
        return []
    records = data if isinstance(data, list) else [data]
    users = _included_users_by_id(payload)
    items: list[SourceItem] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        post_id = str(record.get("id") or "")
        if not post_id:
            continue
        author_id = str(record.get("author_id") or "")
        author = users.get(author_id, {}).get("username") or record.get("author") or query or "unknown"
        urls = _urls_from_entities(record.get("entities"))
        raw = {
            "id": post_id,
            "author": author,
            "author_id": author_id or None,
            "timestamp": record.get("created_at"),
            "text": record.get("text", ""),
            "urls": urls,
            "conversation_id": record.get("conversation_id"),
            "referenced_tweets": record.get("referenced_tweets", []),
            "public_metrics": record.get("public_metrics", {}),
            "source_url": f"https://x.com/{author}/status/{post_id}" if author != "unknown" else None,
        }
        items.append(
            SourceItem(
                source_type="x",
                source_ref=f"x:{post_id}",
                source_url=raw["source_url"],
                raw_fields=raw,
                fetched_at=fetched_at,
            )
        )
    return items


def xurl_auth_available(xurl_path: str = "xurl") -> bool:
    cp = subprocess.run([xurl_path, "auth", "status"], check=False, capture_output=True, text=True, timeout=20)
    return cp.returncode == 0 and ("oauth2:" in cp.stdout or "bearer:" in cp.stdout)


def fetch_x_query(query: str, *, limit: int = 10, xurl_path: str = "xurl") -> dict[str, Any]:
    # No verbose or inline secret flags. xurl reads its normal auth store.
    cp = subprocess.run([xurl_path, "search", query, "-n", str(limit)], check=False, capture_output=True, text=True, timeout=60)
    if cp.returncode != 0:
        raise RuntimeError("xurl search failed; output redacted")
    parsed = json.loads(cp.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError("xurl returned unexpected JSON")
    return parsed


def _included_users_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    includes = payload.get("includes") if isinstance(payload.get("includes"), dict) else {}
    users = includes.get("users") if isinstance(includes.get("users"), list) else []
    return {str(user.get("id")): user for user in users if isinstance(user, dict) and user.get("id")}


def _urls_from_entities(entities: Any) -> list[str]:
    if not isinstance(entities, dict):
        return []
    urls = entities.get("urls") if isinstance(entities.get("urls"), list) else []
    result: list[str] = []
    for item in urls:
        if isinstance(item, dict):
            value = item.get("expanded_url") or item.get("unwound_url") or item.get("url")
            if value:
                result.append(str(value))
    return result


MappingLike = dict[str, Any]
