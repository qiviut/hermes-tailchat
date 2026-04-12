from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INDEX_HTML = REPO / "app" / "static" / "index.html"
TRACEABILITY_SCRIPT = REPO / "scripts" / "traceability_report.py"
SHIP_PR_SCRIPT = REPO / "scripts" / "ship-pr.sh"


def extract_css() -> str:
    html = INDEX_HTML.read_text()
    match = re.search(r"<style>(.*?)</style>", html, re.S)
    assert match, "expected inline stylesheet in index.html"
    return match.group(1)


def css_block(css: str, condition: str) -> str:
    pattern = re.escape(f"@media {condition}") + r"\s*\{(.*?)\n    \}"
    match = re.search(pattern, css, re.S)
    assert match, f"missing media query for {condition}"
    return match.group(1)


def test_traceability_report_reads_requested_range_head() -> None:
    completed = subprocess.run(
        [sys.executable, str(TRACEABILITY_SCRIPT), "HEAD~2..HEAD~1"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Created beads:\n  - hermes-tailchat-cvu:" in completed.stdout
    assert "docs(traceability): add PR template and report tooling" in completed.stdout
    assert "docs(repo): refresh guidance and merge strategy" not in completed.stdout


def test_ship_pr_template_leaves_tests_unchecked_by_default() -> None:
    script = SHIP_PR_SCRIPT.read_text()

    assert "- [ ] `python -m py_compile app/*.py tests/*.py`" in script
    assert "- [ ] `pytest -q tests/test_smoke.py`" in script
    assert "- [x] `python -m py_compile app/*.py tests/*.py`" not in script


def test_mobile_portrait_layout_rules_are_present() -> None:
    css = extract_css()
    tablet_block = css_block(css, "(max-width: 900px)")
    phone_block = css_block(css, "(max-width: 640px)")

    assert "grid-template-columns: 1fr;" in tablet_block
    assert "grid-template-rows: auto minmax(0, 1fr);" in tablet_block
    assert "border-bottom: 1px solid #374151;" in tablet_block
    assert "grid-template-columns: 1fr 1fr;" in tablet_block
    assert "grid-column: 1 / -1;" in tablet_block

    assert "grid-template-columns: 1fr;" in phone_block
    assert "min-height: 96px;" in phone_block
    assert "button {\n        width: 100%;" in phone_block


def test_mobile_landscape_layout_rules_are_present() -> None:
    css = extract_css()
    landscape_block = css_block(css, "(orientation: landscape) and (max-width: 900px)")

    assert "grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);" in landscape_block
    assert "grid-template-rows: none;" in landscape_block
    assert "border-right: 1px solid #374151;" in landscape_block
    assert "border-bottom: 0;" in landscape_block
    assert "grid-template-columns: minmax(0, 1fr) auto auto;" in landscape_block
    assert "grid-column: auto;" in landscape_block
