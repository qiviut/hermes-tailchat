import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_design_doc_exists_and_covers_required_topics():
    path = ROOT / "docs/design/2026-04-13-hermes-codex-multi-agent-coordination.md"
    text = path.read_text()

    required_phrases = [
        "br` / `bv`",
        "Agent Mail",
        "Hermes overseer",
        "Codex worker guidance",
        "sidecar review bead",
        "Testability requirements",
        "Clarification contract: Codex → Hermes",
        "Protocol matrix: who talks to whom, and about what",
        "Recommended initial automated test matrix",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_role_specific_agents_guidance_docs_exist():
    expected = [
        ROOT / "docs/agents/codex-worker-AGENTS.md",
        ROOT / "docs/agents/codex-reviewer-AGENTS.md",
        ROOT / "docs/agents/hermes-overseer-AGENTS.md",
    ]
    for path in expected:
        assert path.exists(), f"missing {path}"
        text = path.read_text()
        assert "Mission" in text


def test_root_agents_points_to_role_specific_guidance():
    text = (ROOT / "AGENTS.md").read_text()
    for relpath in [
        "docs/agents/codex-worker-AGENTS.md",
        "docs/agents/codex-reviewer-AGENTS.md",
        "docs/agents/hermes-overseer-AGENTS.md",
    ]:
        assert relpath in text


def test_message_fixtures_cover_required_contract_fields():
    path = ROOT / "docs/specs/multi-agent-message-fixtures.json"
    data = json.loads(path.read_text())

    clarify = data["clarify"]
    assert clarify["thread_id"]
    assert clarify["subject"].startswith("[clarify][")
    clarify_body = clarify["body"]
    for key in ["goal", "checked", "ambiguity", "options", "recommended_option", "impact_if_unanswered"]:
        assert key in clarify_body

    review_request = data["review_request"]
    assert review_request["subject"].startswith("[review-request][")
    for key in ["goal", "state", "affected_files", "tests_run", "ask"]:
        assert key in review_request["body"]

    lesson = data["lesson"]
    assert lesson["subject"].startswith("[lesson][")
    for key in ["problem", "resolution", "reusable_rule", "suggested_destination"]:
        assert key in lesson["body"]
