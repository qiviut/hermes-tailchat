from __future__ import annotations

import json
import os
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


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def write_issues(repo: Path, *issues: dict[str, str]) -> None:
    beads_dir = repo / ".beads"
    beads_dir.mkdir(exist_ok=True)
    lines = [json.dumps(issue) for issue in issues]
    (beads_dir / "issues.jsonl").write_text("\n".join(lines) + "\n")


def commit(repo: Path, message: str) -> None:
    git(repo, "add", ".")
    git(repo, "commit", "-m", message)


def test_traceability_report_reads_requested_range_head(tmp_path: Path) -> None:
    repo = tmp_path / "traceability-fixture"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Hermes Agent")
    git(repo, "config", "user.email", "hermes@local")

    write_issues(repo, {"id": "hermes-tailchat-a1", "title": "Base bead", "status": "open"})
    commit(repo, "chore: seed issues")

    write_issues(
        repo,
        {"id": "hermes-tailchat-a1", "title": "Base bead", "status": "open"},
        {"id": "hermes-tailchat-b2", "title": "Range head bead", "status": "open"},
    )
    commit(repo, "feat: add range head bead\n\nRefs: hermes-tailchat-b2")

    write_issues(
        repo,
        {"id": "hermes-tailchat-a1", "title": "Base bead", "status": "open"},
        {"id": "hermes-tailchat-b2", "title": "Range head bead", "status": "open"},
        {"id": "hermes-tailchat-c3", "title": "Later head bead", "status": "open"},
    )
    commit(repo, "feat: add later bead\n\nRefs: hermes-tailchat-c3")

    env = os.environ | {"HERMES_TAILCHAT_REPO": str(repo)}
    completed = subprocess.run(
        [sys.executable, str(TRACEABILITY_SCRIPT), "HEAD~2..HEAD~1"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "Created beads:\n  - hermes-tailchat-b2: Range head bead" in completed.stdout
    assert "feat: add range head bead" in completed.stdout
    assert "hermes-tailchat-c3" not in completed.stdout
    assert "feat: add later bead" not in completed.stdout


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
    assert "grid-template-columns: 1fr 1fr 1fr;" in tablet_block
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
    assert "grid-template-columns: minmax(0, 1fr) minmax(140px, 180px) auto auto;" in landscape_block
    assert "grid-column: auto;" in landscape_block


def test_attach_session_picker_ui_is_present() -> None:
    html = INDEX_HTML.read_text()

    assert 'id="attachPanel" class="attach-panel"' in html
    assert 'id="attachList" class="attach-list"' in html
    assert 'id="confirmAttach">Attach selected session</button>' in html
    assert 'id="cancelAttach" class="secondary">Cancel</button>' in html
    assert 'async function openAttachPanel()' in html
    assert 'async function confirmAttach()' in html
    assert 'function closeAttachPanel()' in html
    assert "window.prompt" not in html


def test_attach_session_picker_mobile_layout_rules_are_present() -> None:
    css = extract_css()

    assert '.attach-panel {' in css
    assert '.attach-panel.open {' in css
    assert '.attach-list {' in css
    assert '.attach-actions {' in css
    assert 'grid-template-columns: 1fr 1fr;' in css


def test_attach_session_picker_handles_load_failures() -> None:
    html = INDEX_HTML.read_text()

    assert "if (!res.ok || !Array.isArray(payload))" in html
    assert "attachStatusEl.textContent = payload.detail || 'Failed to load Hermes sessions.';" in html
    assert "Failed to load Hermes sessions:" in html


def test_background_executor_picker_is_present() -> None:
    html = INDEX_HTML.read_text()

    assert 'id="backgroundExecutor"' in html
    assert '>Hermes job<' in html
    assert '>Codex job<' in html
    assert 'executor: backgroundExecutorEl.value' in html


def test_mobile_reconnect_hooks_and_cursor_replay_are_present() -> None:
    html = INDEX_HTML.read_text()

    assert 'let lastEventId = null;' in html
    assert 'eventSource.onerror = () => {' in html
    assert "document.addEventListener('visibilitychange'" in html
    assert "window.addEventListener('online'" in html
    assert "window.addEventListener('offline'" in html
    assert "window.addEventListener('pageshow'" in html
    assert 'events?after_id=${lastEventId}' in html
    assert "setStatus('reconnecting');" in html
