from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from .config import BillingPlan


@dataclass(frozen=True)
class UsageEvent:
    ts: str
    endpoint: str
    target: str
    http_status: int | None
    requests: int
    posts_returned: int
    new_posts: int
    rate_limit_remaining: int | None
    rate_limit_reset: int | None
    estimated_included_reads_used: int


@dataclass(frozen=True)
class UsageForecast:
    month_to_date_reads: int
    month_to_date_requests: int
    included_read_fraction: float | None
    projected_month_end_reads: int
    projected_included_read_fraction: float | None
    estimated_monthly_usd: float


def append_usage_event(path: str | Path, event: UsageEvent) -> None:
    ledger = Path(path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(event), sort_keys=True) + "\n")


def load_usage_events(path: str | Path) -> list[UsageEvent]:
    ledger = Path(path)
    if not ledger.exists():
        return []
    events: list[UsageEvent] = []
    for line in ledger.read_text().splitlines():
        if line.strip():
            events.append(UsageEvent(**json.loads(line)))
    return events


def forecast_usage(events: list[UsageEvent], plan: BillingPlan, *, as_of: str | None = None) -> UsageForecast:
    now = _parse_ts(as_of) if as_of else datetime.now(timezone.utc)
    reads = sum(event.estimated_included_reads_used for event in events)
    requests = sum(event.requests for event in events)
    cycle_start = datetime.fromisoformat(plan.billing_cycle_start).replace(tzinfo=timezone.utc)
    elapsed_days = max((now - cycle_start).total_seconds() / 86400, 1 / 24)
    projected = int(round(reads * (30 / elapsed_days))) if reads else 0
    included_fraction = reads / plan.included_read_posts if plan.included_read_posts else None
    projected_fraction = projected / plan.included_read_posts if plan.included_read_posts else None
    overage_reads = max(0, projected - plan.included_read_posts)
    overage = 0.0
    if plan.overage_usd_per_1000_reads is not None:
        overage = (overage_reads / 1000) * plan.overage_usd_per_1000_reads
    return UsageForecast(
        month_to_date_reads=reads,
        month_to_date_requests=requests,
        included_read_fraction=included_fraction,
        projected_month_end_reads=projected,
        projected_included_read_fraction=projected_fraction,
        estimated_monthly_usd=plan.monthly_usd + overage,
    )


def _parse_ts(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
