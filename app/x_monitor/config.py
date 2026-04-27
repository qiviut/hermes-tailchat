from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WatchAccount:
    handle: str
    priority: int = 2
    sources: list[str] = field(default_factory=lambda: ["user_timeline"])
    poll_interval_minutes: int = 60
    max_results_per_poll: int = 10
    user_id: str | None = None
    enabled: bool = True
    topics: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass(frozen=True)
class GlobalWatchConfig:
    monthly_call_budget: int = 1000
    monthly_read_post_budget: int = 10000
    stop_at_budget_fraction: float = 0.8


@dataclass(frozen=True)
class WatchlistConfig:
    accounts: list[WatchAccount]
    global_config: GlobalWatchConfig = field(default_factory=GlobalWatchConfig)


@dataclass(frozen=True)
class BillingPlan:
    plan_name: str
    monthly_usd: float
    included_read_posts: int
    included_write_posts: int
    overage_usd_per_1000_reads: float | None
    billing_cycle_start: str
    source: str


def load_watchlist(path: str | Path) -> WatchlistConfig:
    data = json.loads(Path(path).read_text())
    accounts = [_parse_account(item) for item in data.get("accounts", [])]
    if not accounts:
        raise ValueError("watchlist must contain at least one account")
    global_config = _parse_global(data.get("global", {}))
    return WatchlistConfig(accounts=accounts, global_config=global_config)


def _parse_account(item: dict[str, Any]) -> WatchAccount:
    handle = str(item.get("handle", "")).strip().lstrip("@")
    if not handle:
        raise ValueError("watch account requires handle")
    max_results = int(item.get("max_results_per_poll", 10))
    if not 1 <= max_results <= 100:
        raise ValueError("max_results_per_poll must be between 1 and 100")
    interval = int(item.get("poll_interval_minutes", 60))
    if interval <= 0:
        raise ValueError("poll_interval_minutes must be positive")
    return WatchAccount(
        handle=handle,
        priority=int(item.get("priority", 2)),
        sources=list(item.get("sources", ["user_timeline"])),
        poll_interval_minutes=interval,
        max_results_per_poll=max_results,
        user_id=str(item["user_id"]) if item.get("user_id") else None,
        enabled=bool(item.get("enabled", True)),
        topics=list(item.get("topics", [])),
        notes=str(item["notes"]) if item.get("notes") is not None else None,
    )


def _parse_global(item: dict[str, Any]) -> GlobalWatchConfig:
    fraction = float(item.get("stop_at_budget_fraction", 0.8))
    if not 0 < fraction <= 1:
        raise ValueError("stop_at_budget_fraction must be > 0 and <= 1")
    return GlobalWatchConfig(
        monthly_call_budget=int(item.get("monthly_call_budget", 1000)),
        monthly_read_post_budget=int(item.get("monthly_read_post_budget", 10000)),
        stop_at_budget_fraction=fraction,
    )


def load_billing_plan(path: str | Path) -> BillingPlan:
    data = json.loads(Path(path).read_text())
    required = ["plan_name", "monthly_usd", "included_read_posts", "included_write_posts", "billing_cycle_start", "source"]
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"billing plan missing required fields: {', '.join(missing)}")
    overage = data.get("overage_usd_per_1000_reads")
    return BillingPlan(
        plan_name=str(data["plan_name"]),
        monthly_usd=float(data["monthly_usd"]),
        included_read_posts=int(data["included_read_posts"]),
        included_write_posts=int(data["included_write_posts"]),
        overage_usd_per_1000_reads=None if overage is None else float(overage),
        billing_cycle_start=str(data["billing_cycle_start"]),
        source=str(data["source"]),
    )
