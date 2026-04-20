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
        "degraded mode",
        "Implementation backlog mapping",
        "hermes-tailchat-v6g",
        "hermes-tailchat-w2n",
        "hermes-tailchat-y5k",
        "hermes-tailchat-z8q",
        "hermes-tailchat-h7m",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_role_specific_agents_guidance_docs_exist_and_are_operational():
    expected = [
        ROOT / "docs/agents/codex-worker-AGENTS.md",
        ROOT / "docs/agents/codex-reviewer-AGENTS.md",
        ROOT / "docs/agents/hermes-overseer-AGENTS.md",
    ]
    for path in expected:
        assert path.exists(), f"missing {path}"
        text = path.read_text()
        assert "Mission" in text
        assert "template" not in text.lower()

    worker_text = (ROOT / "docs/agents/codex-worker-AGENTS.md").read_text()
    for phrase in [
        "Coordinated mode",
        "Degraded mode",
        "Non-trivial change threshold",
        "Definition of done",
        "Do not ask Hermes for routine task selection",
    ]:
        assert phrase in worker_text

    reviewer_text = (ROOT / "docs/agents/codex-reviewer-AGENTS.md").read_text()
    for phrase in [
        "Use the implementation bead ID as the primary `thread_id`",
        "Review disposition recording",
        "Blocking conditions",
    ]:
        assert phrase in reviewer_text

    overseer_text = (ROOT / "docs/agents/hermes-overseer-AGENTS.md").read_text()
    for phrase in [
        "What Hermes should ignore by default",
        "Hermes should not become the routine planner",
        "Hermes is not required for normal child-bead creation",
    ]:
        assert phrase in overseer_text


def test_root_agents_points_to_role_specific_guidance_and_merge_policy():
    text = (ROOT / "AGENTS.md").read_text()
    for relpath in [
        "docs/agents/codex-worker-AGENTS.md",
        "docs/agents/codex-reviewer-AGENTS.md",
        "docs/agents/hermes-overseer-AGENTS.md",
    ]:
        assert relpath in text

    for phrase in [
        "bv --recipe actionable --robot-plan",
        "If `am` is unavailable",
        "review is required before merge",
        "sidecar review improves bead readiness but does not replace repository branch protection",
        "scripts/review_requirements.py",
        "non-trivial",
    ]:
        assert phrase in text


def test_message_contract_spec_and_fixtures_cover_subject_taxonomy_and_envelope():
    spec_path = ROOT / "docs/specs/multi-agent-message-contract.md"
    spec_text = spec_path.read_text()
    for phrase in [
        "Canonical thread anchor",
        "thread_id = implementation bead ID",
        "Envelope fields",
        "Required envelope fields",
        "Optional envelope fields",
        "Subject taxonomy",
        "worker_to_worker",
        "worker_to_hermes",
        "hermes_to_worker",
        "[start][bead-id]",
        "[review-request][bead-id]",
        "[clarify][bead-id]",
        "[decision][bead-id]",
        "Body contract",
        "Routing expectations",
        "docs/specs/multi-agent-message-fixtures.json",
    ]:
        assert phrase in spec_text

    path = ROOT / "docs/specs/multi-agent-message-fixtures.json"
    data = json.loads(path.read_text())

    assert data["schema_version"] == 1
    common_fields = data["common_envelope_fields"]
    for field in [
        "schema_version",
        "message_id",
        "project_key",
        "thread_id",
        "from",
        "to",
        "subject",
        "related_bead_ids",
        "body",
        "created_at",
    ]:
        assert field in common_fields

    optional_fields = data["optional_envelope_fields"]
    for field in ["reply_to", "in_reply_to", "metadata"]:
        assert field in optional_fields

    taxonomy = data["subject_taxonomy"]
    assert taxonomy["canonical_thread_anchor"] == "implementation_bead_id"
    assert taxonomy["worker_to_worker"] == [
        "start",
        "handoff",
        "review-request",
        "review-feedback",
        "blocker",
        "done",
    ]
    assert taxonomy["worker_to_hermes"] == [
        "clarify",
        "escalation",
        "lesson",
        "memory-request",
    ]
    assert taxonomy["hermes_to_worker"] == [
        "decision",
        "policy",
        "split-guidance",
        "escalate-human",
    ]

    body_contract = data["body_contract"]
    for field in ["goal", "state", "recommended_next_step"]:
        assert field in body_contract["always"]
    for key in [
        "start",
        "handoff",
        "review-request",
        "review-feedback",
        "blocker",
        "done",
        "clarify",
        "escalation",
        "lesson",
        "memory-request",
        "decision",
        "policy",
        "split-guidance",
        "escalate-human",
    ]:
        assert key in body_contract["per_subject"]

    required_message_types = [
        "start",
        "handoff",
        "review_request",
        "review_feedback",
        "blocker",
        "done",
        "clarify",
        "escalation",
        "lesson",
        "memory_request",
        "decision",
        "policy",
        "split_guidance",
        "escalate_human",
    ]
    for key in required_message_types:
        assert key in data, f"missing fixture {key}"
        fixture = data[key]
        for envelope_key in common_fields:
            assert envelope_key in fixture, f"{key} missing {envelope_key}"
        assert fixture["thread_id"] in fixture["subject"]
        assert fixture["related_bead_ids"]
        assert fixture["project_key"] == "hermes-tailchat"
        assert fixture["message_id"].startswith("msg-")

    clarify = data["clarify"]
    assert clarify["subject"].startswith("[clarify][")
    clarify_body = clarify["body"]
    for key in [
        "goal",
        "state",
        "checked",
        "ambiguity",
        "options",
        "recommended_option",
        "affected_files",
        "impact_if_unanswered",
        "recommended_next_step",
    ]:
        assert key in clarify_body

    review_request = data["review_request"]
    assert review_request["subject"].startswith("[review-request][")
    for key in ["goal", "state", "affected_files", "tests_run", "ask", "recommended_next_step"]:
        assert key in review_request["body"]

    lesson = data["lesson"]
    assert lesson["subject"].startswith("[lesson][")
    for key in ["goal", "state", "problem", "resolution", "reusable_rule", "suggested_destination", "recommended_next_step"]:
        assert key in lesson["body"]

    blocker = data["blocker"]
    assert blocker["subject"].startswith("[blocker][")
    for key in ["goal", "state", "affected_files", "ask", "recommended_next_step"]:
        assert key in blocker["body"]

    done = data["done"]
    assert done["subject"].startswith("[done][")
    for key in ["goal", "state", "review_outcome", "evidence_checked", "recommended_next_step"]:
        assert key in done["body"]

    decision = data["decision"]
    assert decision["subject"].startswith("[decision][")
    assert decision["body"]["decision"]
    assert decision["body"]["recommended_next_step"]


def test_implementation_plan_exists_and_matches_design_backlog():
    path = ROOT / "docs/plans/2026-04-14-multi-agent-coordination-implementation.md"
    text = path.read_text()
    for phrase in [
        "hermes-tailchat-dnl",
        "hermes-tailchat-w2n",
        "hermes-tailchat-v6g",
        "hermes-tailchat-y5k",
        "hermes-tailchat-z8q",
        "hermes-tailchat-h7m",
        "Testability anchors",
    ]:
        assert phrase in text


def test_bead_graph_contains_new_enabling_slices_for_multi_agent_work():
    issues_path = ROOT / ".beads/issues.jsonl"
    issues = [json.loads(line) for line in issues_path.read_text().splitlines() if line.strip()]
    by_id = {issue["id"]: issue for issue in issues}

    for bead_id in [
        "hermes-tailchat-bar",
        "hermes-tailchat-v6g",
        "hermes-tailchat-w2n",
        "hermes-tailchat-y5k",
        "hermes-tailchat-z8q",
        "hermes-tailchat-h7m",
    ]:
        assert bead_id in by_id, f"missing bead {bead_id}"

    for bead_id in [
        "hermes-tailchat-v6g",
        "hermes-tailchat-w2n",
        "hermes-tailchat-y5k",
        "hermes-tailchat-z8q",
        "hermes-tailchat-h7m",
    ]:
        assert by_id[bead_id]["status"] != "cancelled"

    v6g_deps = by_id["hermes-tailchat-v6g"].get("dependencies", [])
    assert any(dep["depends_on_id"] == "hermes-tailchat-bar" and dep["type"] == "parent-child" for dep in v6g_deps)

    w2n_deps = by_id["hermes-tailchat-w2n"].get("dependencies", [])
    assert any(dep["depends_on_id"] == "hermes-tailchat-bar" and dep["type"] == "parent-child" for dep in w2n_deps)

    y5k_deps = by_id["hermes-tailchat-y5k"].get("dependencies", [])
    assert any(dep["depends_on_id"] == "hermes-tailchat-3wt" and dep["type"] == "parent-child" for dep in y5k_deps)

    z8q_deps = by_id["hermes-tailchat-z8q"].get("dependencies", [])
    assert any(dep["depends_on_id"] == "hermes-tailchat-3wt" and dep["type"] == "parent-child" for dep in z8q_deps)

    h7m_deps = by_id["hermes-tailchat-h7m"].get("dependencies", [])
    assert any(dep["depends_on_id"] == "hermes-tailchat-lx3" and dep["type"] == "parent-child" for dep in h7m_deps)
