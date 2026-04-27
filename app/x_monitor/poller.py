from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from app.untrusted_ingest import inspect_payload

from .config import WatchAccount


class JsonClient(Protocol):
    def get_json(self, endpoint: str) -> dict[str, Any]: ...


@dataclass
class PollState:
    user_ids: dict[str, str] = field(default_factory=dict)
    last_seen_post_ids: dict[str, str] = field(default_factory=dict)
    seen_post_ids: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class PollResult:
    handle: str
    user_id: str
    posts_returned: int
    new_posts: int
    new_post_ids: list[str]
    raw_paths: list[str]
    normalized_paths: list[str]
    newest_id: str | None


def load_state(path: str | Path) -> PollState:
    state_path = Path(path)
    if not state_path.exists():
        return PollState()
    data = json.loads(state_path.read_text())
    return PollState(
        user_ids=dict(data.get("user_ids", {})),
        last_seen_post_ids=dict(data.get("last_seen_post_ids", {})),
        seen_post_ids={key: list(value) for key, value in data.get("seen_post_ids", {}).items()},
    )


def save_state(path: str | Path, state: PollState) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "user_ids": state.user_ids,
        "last_seen_post_ids": state.last_seen_post_ids,
        "seen_post_ids": state.seen_post_ids,
    }, indent=2, sort_keys=True) + "\n")


def poll_account_once(
    *,
    client: JsonClient,
    account: WatchAccount,
    state: PollState,
    spool_root: str | Path,
    fetched_at: str | None = None,
) -> PollResult:
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    handle = account.handle.lstrip("@")
    user_id = account.user_id or state.user_ids.get(handle)
    if not user_id:
        user_payload = client.get_json(f"/2/users/by/username/{quote(handle)}?user.fields=id,username")
        user_id = str(user_payload.get("data", {}).get("id", ""))
        if not user_id:
            raise RuntimeError(f"X user lookup for @{handle} did not return an id")
        state.user_ids[handle] = user_id

    endpoint = (
        f"/2/users/{quote(user_id)}/tweets"
        f"?max_results={account.max_results_per_poll}"
        "&tweet.fields=created_at,conversation_id,entities,referenced_tweets"
        "&exclude=retweets,replies"
    )
    payload = client.get_json(endpoint)
    posts = [item for item in payload.get("data", []) if isinstance(item, dict)]
    seen = set(state.seen_post_ids.get(handle, []))
    last_seen = state.last_seen_post_ids.get(handle)
    new_items: list[dict[str, Any]] = []
    for post in posts:
        post_id = str(post.get("id", ""))
        if not post_id or post_id in seen:
            continue
        if last_seen and post_id == last_seen:
            continue
        new_items.append(post)

    root = Path(spool_root)
    raw_paths: list[str] = []
    normalized_paths: list[str] = []
    for post in new_items:
        post_id = str(post["id"])
        raw_payload = {"handle": handle, "user_id": user_id, "post": post, "fetched_at": fetched_at}
        raw_path = _write_json(root / "raw" / "x" / handle / f"{post_id}.json", raw_payload)
        normalized_payload = _to_untrusted_x_payload(handle, post)
        artifact = inspect_payload(normalized_payload, source_type="x", source_ref=f"x:{post_id}", fetched_at=fetched_at)
        flags = artifact.setdefault("deterministic_flags", [])
        if "untrusted_input" not in flags:
            flags.append("untrusted_input")
            artifact["deterministic_flags"] = sorted(flags)
        normalized_path = _write_json(root / "normalized" / "x" / handle / f"{post_id}.json", artifact)
        raw_paths.append(str(raw_path))
        normalized_paths.append(str(normalized_path))
        seen.add(post_id)

    if posts:
        newest = str(posts[0].get("id", "")) or None
        if newest:
            state.last_seen_post_ids[handle] = newest
    else:
        newest = None
    state.seen_post_ids[handle] = sorted(seen, reverse=True)[:1000]

    return PollResult(
        handle=handle,
        user_id=user_id,
        posts_returned=len(posts),
        new_posts=len(new_items),
        new_post_ids=[str(item["id"]) for item in new_items],
        raw_paths=raw_paths,
        normalized_paths=normalized_paths,
        newest_id=newest,
    )


def _to_untrusted_x_payload(handle: str, post: dict[str, Any]) -> dict[str, Any]:
    entities = post.get("entities") if isinstance(post.get("entities"), dict) else {}
    urls = []
    for item in entities.get("urls", []) if isinstance(entities.get("urls"), list) else []:
        if isinstance(item, dict):
            urls.append(item.get("expanded_url") or item.get("url"))
    return {
        "author": handle,
        "timestamp": post.get("created_at"),
        "text": post.get("text", ""),
        "urls": [url for url in urls if url],
        "conversation_id": post.get("conversation_id"),
        "media": [],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def stable_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
