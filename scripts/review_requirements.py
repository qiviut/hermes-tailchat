#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(os.environ.get("HERMES_TAILCHAT_REPO", Path(__file__).resolve().parents[1])).resolve()
DOC_TEST_PREFIXES = (
    "docs/",
    "tests/",
)
EXECUTABLE_PREFIXES = (
    "app/",
    "scripts/",
)
POLICY_PREFIXES = (
    ".github/workflows/",
    "docs/agents/",
    "docs/policies/",
)
POLICY_FILES = {
    "AGENTS.md",
    "scripts/ship-pr.sh",
    "scripts/traceability_report.py",
    "scripts/review_requirements.py",
}
LOW_RISK_FILES = {
    ".gitignore",
    ".editorconfig",
    "LICENSE",
}


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.input:
        return json.loads(Path(args.input).read_text())

    changed_files = args.changed_file or list_changed_files(args.rev_range)
    return {
        "bead_id": args.bead_id,
        "changed_files": changed_files,
        "review_bead_id": args.review_bead_id,
    }


def list_changed_files(rev_range: str | None) -> list[str]:
    diff_target = rev_range or "--cached"
    command = ["git", "diff", "--name-only"]
    if diff_target == "--cached":
        command.append("--cached")
    else:
        command.append(diff_target)
    completed = subprocess.run(
        command,
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def is_doc_or_test_only(path: str) -> bool:
    return path == "README.md" or path.startswith(DOC_TEST_PREFIXES)


def changes_executable_behavior(path: str) -> bool:
    return path.startswith(EXECUTABLE_PREFIXES)


def changes_policy_or_workflow(path: str) -> bool:
    return path.startswith(POLICY_PREFIXES) or path in POLICY_FILES


def is_low_risk_non_executable(path: str) -> bool:
    return path in LOW_RISK_FILES


def is_opaque_or_stateful_artifact(path: str) -> bool:
    return path.endswith(".db") or path.endswith(".sqlite") or path.endswith(".sqlite3")


def file_cluster(path: str) -> str:
    if path == "README.md":
        return "docs"
    if path == "AGENTS.md":
        return "agent_docs"
    if path.startswith("app/"):
        return "app"
    if path.startswith("scripts/"):
        return "scripts"
    if path.startswith("docs/agents/"):
        return "agent_docs"
    if path.startswith("docs/policies/"):
        return "policy_docs"
    if path.startswith("docs/"):
        return "docs"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith(".github/"):
        return "github"
    return path.split("/", 1)[0]


def classify_change(changed_files: list[str], bead_id: str | None, review_bead_id: str | None) -> dict[str, Any]:
    changed_files = sorted(dict.fromkeys(path for path in changed_files if path))
    reasons: list[str] = []
    clusters = {file_cluster(path) for path in changed_files}

    if not changed_files:
        return {
            "bead_id": bead_id,
            "changed_files": changed_files,
            "file_clusters": [],
            "classification": "unscoped",
            "reasons": ["no_changed_files"],
            "requires_sidecar_review": False,
            "review_bead_id": review_bead_id,
            "sidecar_review_status": "unknown",
            "ready_to_close": False,
        }

    if all(is_doc_or_test_only(path) for path in changed_files) and len(clusters) == 1 and not any(changes_policy_or_workflow(path) for path in changed_files):
        reasons.append("docs_or_tests_only")
    else:
        if any(changes_executable_behavior(path) for path in changed_files):
            reasons.append("changes_executable_behavior")
        if len(clusters) > 1:
            reasons.append("spans_multiple_file_clusters")
        if any(changes_policy_or_workflow(path) for path in changed_files):
            reasons.append("changes_policy_or_workflow")
        if any(path.startswith("tests/") for path in changed_files) and any(not is_doc_or_test_only(path) for path in changed_files):
            reasons.append("introduces_or_updates_regression_obligations")
        if any(is_opaque_or_stateful_artifact(path) for path in changed_files):
            reasons.append("opaque_or_stateful_artifact")
        if not reasons and all(is_low_risk_non_executable(path) for path in changed_files):
            reasons.append("single_cluster_low_risk_change")
        if not reasons:
            reasons.append("unclassified_non_trivial_change")

    non_trivial = any(reason in {
        "changes_executable_behavior",
        "spans_multiple_file_clusters",
        "changes_policy_or_workflow",
        "introduces_or_updates_regression_obligations",
        "opaque_or_stateful_artifact",
        "unclassified_non_trivial_change",
    } for reason in reasons)
    requires_sidecar_review = non_trivial

    if requires_sidecar_review:
        sidecar_review_status = "present" if review_bead_id else "missing"
        ready_to_close = bool(review_bead_id)
    else:
        sidecar_review_status = "not_required"
        ready_to_close = True

    return {
        "bead_id": bead_id,
        "changed_files": changed_files,
        "file_clusters": sorted(clusters),
        "classification": "non_trivial" if non_trivial else "trivial",
        "reasons": reasons,
        "requires_sidecar_review": requires_sidecar_review,
        "review_bead_id": review_bead_id,
        "sidecar_review_status": sidecar_review_status,
        "ready_to_close": ready_to_close,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify a change and determine whether sidecar review is required.")
    parser.add_argument("--input", help="Path to JSON payload with bead_id, changed_files, and optional review_bead_id")
    parser.add_argument("--bead-id")
    parser.add_argument("--review-bead-id")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--rev-range", help="Git revision range to inspect; defaults to staged changes via git diff --cached --name-only")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    payload = load_payload(args)
    result = classify_change(
        changed_files=payload.get("changed_files") or [],
        bead_id=payload.get("bead_id"),
        review_bead_id=payload.get("review_bead_id"),
    )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result["ready_to_close"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
