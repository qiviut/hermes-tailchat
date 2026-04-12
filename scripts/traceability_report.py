#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BEAD_RE = re.compile(r"\bhermes-tailchat-[a-z0-9]+\b")


def run(*args: str, allow_fail: bool = False) -> str:
    proc = subprocess.run(args, cwd=REPO, text=True, capture_output=True)
    if proc.returncode != 0 and not allow_fail:
        raise subprocess.CalledProcessError(proc.returncode, args, output=proc.stdout, stderr=proc.stderr)
    return proc.stdout


def parse_issues_at(rev: str) -> dict[str, dict]:
    text = run("git", "show", f"{rev}:.beads/issues.jsonl", allow_fail=True)
    if not text:
        return {}
    issues = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        issues[item["id"]] = item
    return issues


def parse_current_issues() -> dict[str, dict]:
    path = REPO / ".beads" / "issues.jsonl"
    issues = {}
    if not path.exists():
        return issues
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        issues[item["id"]] = item
    return issues


def commits_in_range(rev_range: str) -> list[dict]:
    fmt = "%H%x1f%s%x1f%b%x1e"
    raw = run("git", "log", "--reverse", f"--format={fmt}", rev_range)
    commits = []
    for chunk in raw.split("\x1e"):
        chunk = chunk.strip()
        if not chunk:
            continue
        sha, subject, body = chunk.split("\x1f", 2)
        beads = sorted(set(BEAD_RE.findall(subject + "\n" + body)))
        commits.append({"sha": sha, "subject": subject, "body": body.strip(), "beads": beads})
    return commits


def classify_changes(before: dict[str, dict], after: dict[str, dict]) -> dict[str, list[str]]:
    created = []
    progressed = []
    completed = []
    reopened = []
    for bead_id, after_item in after.items():
        before_item = before.get(bead_id)
        if before_item is None:
            created.append(bead_id)
            continue
        b = before_item.get("status")
        a = after_item.get("status")
        if b != a:
            if a == "closed":
                completed.append(bead_id)
            elif a == "in_progress":
                progressed.append(bead_id)
            elif b == "closed" and a != "closed":
                reopened.append(bead_id)
    return {
        "created": sorted(created),
        "progressed": sorted(progressed),
        "completed": sorted(completed),
        "reopened": sorted(reopened),
    }


def title_map(issues: dict[str, dict]) -> dict[str, str]:
    return {k: v.get("title", "") for k, v in issues.items()}


def print_section(title: str, ids: list[str], titles: dict[str, str]) -> None:
    print(f"\n{title}:")
    if not ids:
        print("  (none)")
        return
    for bead_id in ids:
        print(f"  - {bead_id}: {titles.get(bead_id, '')}")


def main() -> int:
    rev_range = sys.argv[1] if len(sys.argv) > 1 else "main..HEAD"
    if ".." in rev_range:
        base, head = rev_range.split("..", 1)
    else:
        base = f"{rev_range}^"
        head = rev_range
    before = parse_issues_at(base)
    after = parse_issues_at(head) if head != "HEAD" else parse_current_issues()
    changes = classify_changes(before, after)
    titles = title_map(after | before)
    commits = commits_in_range(rev_range)

    print(f"Traceability report for {rev_range}")
    print_section("Created beads", changes["created"], titles)
    print_section("Progressed beads", changes["progressed"], titles)
    print_section("Completed beads", changes["completed"], titles)
    print_section("Reopened beads", changes["reopened"], titles)

    print("\nCommits and referenced beads:")
    if not commits:
        print("  (no commits in range)")
        return 0
    for commit in commits:
        short = commit["sha"][:8]
        print(f"  - {short} {commit['subject']}")
        if commit["beads"]:
            for bead_id in commit["beads"]:
                print(f"      refs {bead_id}: {titles.get(bead_id, '')}")
        else:
            print("      refs none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
