#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.x_monitor.config import BillingPlan, WatchAccount, load_billing_plan, load_watchlist
from app.x_monitor.costs import UsageEvent, append_usage_event, forecast_usage, load_usage_events
from app.x_monitor.poller import PollState, load_state, poll_account_once, save_state
from app.x_monitor.xurl_client import XurlClient, build_temp_xurl_home

DEFAULT_SECRET = Path.home() / ".config/hermes/secrets/x-api/hermes-93610471048.env"


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor high-value X accounts with cost tracking and untrusted-ingestion spooling.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check-config", help="Validate watchlist and optional billing config")
    check.add_argument("--watchlist", required=True)
    check.add_argument("--billing")

    poll = sub.add_parser("poll", help="Poll enabled watchlist accounts")
    poll.add_argument("--watchlist", required=True)
    poll.add_argument("--secret-file", default=str(DEFAULT_SECRET))
    poll.add_argument("--spool-root", default="data/x")
    poll.add_argument("--state", default="data/x/state.json")
    poll.add_argument("--ledger", default="data/x/usage.jsonl")
    poll.add_argument("--dry-run", action="store_true")
    poll.add_argument("--account", help="Only poll this handle")

    report = sub.add_parser("report-costs", help="Report usage and monthly forecast")
    report.add_argument("--ledger", default="data/x/usage.jsonl")
    report.add_argument("--billing", required=True)

    smoke = sub.add_parser("smoke", help="Smoke-test app bearer auth without printing raw X content")
    smoke.add_argument("--secret-file", default=str(DEFAULT_SECRET))
    smoke.add_argument("--handle", default="swyx")

    args = parser.parse_args()
    if args.cmd == "check-config":
        watchlist = load_watchlist(args.watchlist)
        result: dict[str, object] = {"accounts": len(watchlist.accounts), "handles": [a.handle for a in watchlist.accounts]}
        if args.billing:
            plan = load_billing_plan(args.billing)
            result["billing_plan"] = plan.plan_name
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.cmd == "poll":
        return _poll(args)
    if args.cmd == "report-costs":
        return _report(args)
    if args.cmd == "smoke":
        return _smoke(args)
    raise AssertionError(args.cmd)


def _poll(args: argparse.Namespace) -> int:
    watchlist = load_watchlist(args.watchlist)
    accounts = [a for a in watchlist.accounts if a.enabled]
    if args.account:
        wanted = args.account.lstrip("@")
        accounts = [a for a in accounts if a.handle == wanted]
    if args.dry_run:
        print(json.dumps({"dry_run": True, "accounts": [asdict(a) for a in accounts]}, indent=2, sort_keys=True))
        return 0

    secrets = _load_secret_file(Path(args.secret_file))
    state = load_state(args.state)
    fetched_at = _now()
    summaries = []
    with build_temp_xurl_home(
        app_name=secrets["X_APP_NAME"],
        client_id=secrets["X_CONSUMER_KEY"],
        client_secret=secrets["X_SECRET_KEY"],
        bearer_token=secrets["X_BEARER_TOKEN"],
    ) as home:
        client = XurlClient(xurl_path=_xurl_path(), home=home, app_name=secrets["X_APP_NAME"], auth="app")
        for account in accounts:
            had_user_id = bool(account.user_id or state.user_ids.get(account.handle))
            result = poll_account_once(client=client, account=account, state=state, spool_root=args.spool_root, fetched_at=fetched_at)
            append_usage_event(
                args.ledger,
                UsageEvent(
                    ts=fetched_at,
                    endpoint="/2/users/:id/tweets",
                    target=account.handle,
                    http_status=200,
                    requests=1 if had_user_id else 2,
                    posts_returned=result.posts_returned,
                    new_posts=result.new_posts,
                    rate_limit_remaining=None,
                    rate_limit_reset=None,
                    estimated_included_reads_used=result.posts_returned,
                ),
            )
            summaries.append(
                {
                    "handle": result.handle,
                    "user_id": result.user_id,
                    "posts_returned": result.posts_returned,
                    "new_posts": result.new_posts,
                    "new_post_ids": result.new_post_ids,
                    "newest_id": result.newest_id,
                }
            )
    save_state(args.state, state)
    print(json.dumps({"fetched_at": fetched_at, "results": summaries}, indent=2, sort_keys=True))
    return 0


def _report(args: argparse.Namespace) -> int:
    plan = load_billing_plan(args.billing)
    events = load_usage_events(args.ledger)
    forecast = forecast_usage(events, plan)
    print(json.dumps(asdict(forecast), indent=2, sort_keys=True))
    return 0


def _smoke(args: argparse.Namespace) -> int:
    secrets = _load_secret_file(Path(args.secret_file))
    handle = args.handle.lstrip("@")
    with build_temp_xurl_home(
        app_name=secrets["X_APP_NAME"],
        client_id=secrets["X_CONSUMER_KEY"],
        client_secret=secrets["X_SECRET_KEY"],
        bearer_token=secrets["X_BEARER_TOKEN"],
    ) as home:
        client = XurlClient(xurl_path=_xurl_path(), home=home, app_name=secrets["X_APP_NAME"], auth="app")
        payload = client.get_json(f"/2/users/by/username/{handle}?user.fields=id,username,name,verified,verified_type,created_at")
    data = payload.get("data", {})
    safe = {k: data.get(k) for k in ["id", "username", "name", "verified", "verified_type", "created_at"] if k in data}
    print(json.dumps({"ok": True, "data": safe}, indent=2, sort_keys=True))
    return 0


def _load_secret_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    required = ["X_APP_NAME", "X_CONSUMER_KEY", "X_SECRET_KEY", "X_BEARER_TOKEN"]
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise SystemExit(f"secret file missing required keys: {', '.join(missing)}")
    return values


def _xurl_path() -> str:
    candidate = Path.home() / "go/bin/xurl"
    if candidate.exists():
        return str(candidate)
    return "xurl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
