from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_VALID_CONFIDENCE = {"low", "medium", "high"}
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
_REQUIRED = {
    "source_refs",
    "claim",
    "evidence",
    "skill_trigger",
    "workflow_steps",
    "tooling",
    "risk_notes",
    "confidence",
    "proposed_skill_name",
}


class CandidateValidationError(ValueError):
    pass


def validate_candidate(candidate: dict[str, Any]) -> None:
    missing = sorted(_REQUIRED - set(candidate))
    if missing:
        raise CandidateValidationError(f"candidate missing required fields: {', '.join(missing)}")
    if not isinstance(candidate["source_refs"], list) or not candidate["source_refs"]:
        raise CandidateValidationError("source_refs must be a non-empty list")
    if candidate["confidence"] not in _VALID_CONFIDENCE:
        raise CandidateValidationError("confidence must be low, medium, or high")
    if not _NAME_RE.match(str(candidate["proposed_skill_name"])):
        raise CandidateValidationError("proposed_skill_name must be lowercase-hyphen style")
    if not isinstance(candidate["workflow_steps"], list) or not candidate["workflow_steps"]:
        raise CandidateValidationError("workflow_steps must be a non-empty list")


def sanitize_skill_name(value: str) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    name = re.sub(r"-+", "-", name)[:64].strip("-")
    return name or "swyx-candidate-skill"


def render_skill_draft(candidate: dict[str, Any]) -> str:
    validate_candidate(candidate)
    name = sanitize_skill_name(str(candidate["proposed_skill_name"]))
    description = str(candidate["skill_trigger"]).strip().replace('"', "'")[:240]
    lines = [
        "---",
        f"name: {name}",
        f"description: \"{description}\"",
        "metadata:",
        "  hermes:",
        "    tags: [swyx, candidate, agent-workflow]",
        "    status: draft-review-required",
        "---",
        "",
        f"# {name}",
        "",
        "## Review status",
        "",
        "This draft was generated from untrusted external content and must be reviewed before installation.",
        "",
        "## Claim",
        "",
        str(candidate["claim"]).strip(),
        "",
        "## When to use",
        "",
        str(candidate["skill_trigger"]).strip(),
        "",
        "## Workflow",
        "",
    ]
    lines.extend(f"{idx}. {step}" for idx, step in enumerate(candidate["workflow_steps"], start=1))
    lines.extend(["", "## Tooling", ""])
    tooling = candidate.get("tooling") or []
    lines.extend(f"- {tool}" for tool in tooling) if tooling else lines.append("- TODO: confirm tooling during review")
    lines.extend(["", "## Evidence", ""])
    for evidence in candidate.get("evidence") or []:
        if isinstance(evidence, dict):
            quote = str(evidence.get("quote", "")).strip()[:300]
            ref = str(evidence.get("source_ref", "unknown"))
            stamp = f" @ {evidence['timestamp']}" if evidence.get("timestamp") else ""
            lines.append(f"- {ref}{stamp}: {quote}")
    lines.extend(["", "## Risks", ""])
    risk_notes = candidate.get("risk_notes") or ["Generated from untrusted input; verify before promotion."]
    lines.extend(f"- {risk}" for risk in risk_notes)
    lines.extend(["", "## Verification", "", "- Validate frontmatter and trigger quality before promotion.", "- Confirm evidence links and rewrite any TODOs.", ""])
    return "\n".join(lines)


def write_skill_draft(root: str | Path, candidate: dict[str, Any]) -> Path:
    name = sanitize_skill_name(str(candidate.get("proposed_skill_name", "swyx-candidate-skill")))
    path = Path(root) / "drafts" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_skill_draft(candidate))
    return path
