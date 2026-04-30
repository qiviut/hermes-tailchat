from __future__ import annotations

import json
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
    _require_string(candidate, "claim")
    _require_string(candidate, "skill_trigger")
    _require_string(candidate, "proposed_skill_name")
    if not isinstance(candidate["source_refs"], list) or not candidate["source_refs"] or not all(isinstance(value, str) and value.strip() for value in candidate["source_refs"]):
        raise CandidateValidationError("source_refs must be a non-empty list of strings")
    if candidate["confidence"] not in _VALID_CONFIDENCE:
        raise CandidateValidationError("confidence must be low, medium, or high")
    if not _NAME_RE.match(str(candidate["proposed_skill_name"])):
        raise CandidateValidationError("proposed_skill_name must be lowercase-hyphen style")
    if not isinstance(candidate["workflow_steps"], list) or not candidate["workflow_steps"] or not all(isinstance(value, str) and value.strip() for value in candidate["workflow_steps"]):
        raise CandidateValidationError("workflow_steps must be a non-empty list of strings")
    for field in ("tooling", "risk_notes"):
        if not isinstance(candidate[field], list) or not all(isinstance(value, str) and value.strip() for value in candidate[field]):
            raise CandidateValidationError(f"{field} must be a list of strings")
    if not isinstance(candidate["evidence"], list) or not candidate["evidence"]:
        raise CandidateValidationError("evidence must be a non-empty list")
    for item in candidate["evidence"]:
        if not isinstance(item, dict) or not isinstance(item.get("source_ref"), str) or not isinstance(item.get("quote"), str) or not item.get("quote", "").strip():
            raise CandidateValidationError("evidence entries must include source_ref and quote strings")


def _require_string(candidate: dict[str, Any], field: str) -> None:
    if not isinstance(candidate[field], str) or not candidate[field].strip():
        raise CandidateValidationError(f"{field} must be a non-empty string")


def safe_text(value: Any, *, max_chars: int = 500) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def yaml_string(value: Any, *, max_chars: int = 500) -> str:
    return json.dumps(safe_text(value, max_chars=max_chars), ensure_ascii=False)


def sanitize_skill_name(value: str) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    name = re.sub(r"-+", "-", name)[:64].strip("-")
    return name or "swyx-candidate-skill"


def render_skill_draft(candidate: dict[str, Any]) -> str:
    validate_candidate(candidate)
    name = sanitize_skill_name(str(candidate["proposed_skill_name"]))
    description = safe_text(candidate["skill_trigger"], max_chars=240)
    lines = [
        "---",
        f"name: {name}",
        f"description: {yaml_string(description, max_chars=240)}",
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
        safe_text(candidate["claim"], max_chars=500),
        "",
        "## When to use",
        "",
        safe_text(candidate["skill_trigger"], max_chars=500),
        "",
        "## Workflow",
        "",
    ]
    lines.extend(f"{idx}. {safe_text(step, max_chars=500)}" for idx, step in enumerate(candidate["workflow_steps"], start=1))
    lines.extend(["", "## Tooling", ""])
    tooling = candidate.get("tooling") or []
    lines.extend(f"- {safe_text(tool, max_chars=120)}" for tool in tooling) if tooling else lines.append("- TODO: confirm tooling during review")
    lines.extend(["", "## Evidence", ""])
    for evidence in candidate.get("evidence") or []:
        quote = safe_text(evidence.get("quote", ""), max_chars=300)
        ref = safe_text(evidence.get("source_ref", "unknown"), max_chars=120)
        stamp = f" @ {safe_text(evidence['timestamp'], max_chars=80)}" if evidence.get("timestamp") else ""
        lines.append(f"- {ref}{stamp}: {quote}")
    lines.extend(["", "## Risks", ""])
    risk_notes = candidate.get("risk_notes") or ["Generated from untrusted input; verify before promotion."]
    lines.extend(f"- {safe_text(risk, max_chars=300)}" for risk in risk_notes)
    lines.extend(["", "## Verification", "", "- Validate frontmatter and trigger quality before promotion.", "- Confirm evidence links and rewrite any TODOs.", ""])
    return "\n".join(lines)


def write_skill_draft(root: str | Path, candidate: dict[str, Any]) -> Path:
    name = sanitize_skill_name(str(candidate.get("proposed_skill_name", "swyx-candidate-skill")))
    path = Path(root) / "drafts" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_skill_draft(candidate))
    return path
