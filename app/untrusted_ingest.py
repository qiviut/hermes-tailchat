from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = BASE_DIR / "config" / "untrusted_ingest" / "pipelines"

URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
DOMAIN_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b", re.IGNORECASE)
COMMAND_RE = re.compile(
    r"\b(?:curl|wget|bash|sh|python|python3|node|npm|pnpm|yarn|pip|pip3|git|gh|docker|kubectl|terraform|tofu|ssh|scp|rsync|make)\b[^\n]{0,160}",
    re.IGNORECASE,
)
SECRET_PATTERNS: dict[str, str] = {
    "aws_access_key": r"\bAKIA[0-9A-Z]{16}\b",
    "github_token": r"\bgh[psu]_[A-Za-z0-9]{20,}\b",
    "slack_token": r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",
    "openai_project_key": r"\bsk-proj-[A-Za-z0-9_-]{16,}\b",
    "generic_bearer": r"\bBearer\s+[A-Za-z0-9._=-]{16,}\b",
}
TRUNCATION_MARKER = "\n… [truncated by untrusted ingest]"


@dataclass(frozen=True)
class PipelineConfig:
    source_type: str
    config: dict[str, Any]
    path: Path


class UntrustedIngestError(RuntimeError):
    pass


class PipelineNotFoundError(UntrustedIngestError):
    pass


def available_pipelines() -> list[str]:
    if not PIPELINE_DIR.exists():
        return []
    return sorted(path.stem for path in PIPELINE_DIR.glob("*.json"))


def load_pipeline_config(source_type: str) -> PipelineConfig:
    candidates = [source_type]
    for path in PIPELINE_DIR.glob("*.json"):
        config = json.loads(path.read_text())
        aliases = config.get("aliases", [])
        if source_type == config.get("source_type") or source_type in aliases:
            return PipelineConfig(source_type=config["source_type"], config=config, path=path)
        candidates.append(path.stem)
    raise PipelineNotFoundError(
        f"Unknown source_type {source_type!r}. Available pipelines: {', '.join(sorted(set(candidates)))}"
    )


def inspect_payload(
    payload: Any,
    *,
    source_type: str,
    source_ref: str,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    pipeline = load_pipeline_config(source_type)
    projected = _project_payload(payload, pipeline.config)
    text, structured_fields = _normalize_projected(projected, pipeline.config)
    domains = _extract_domains(text)
    commands = _extract_commands(text, pipeline.config)
    secret_findings = _detect_secret_like_patterns(text, pipeline.config)
    normalized_text, truncation = _enforce_budget(text, pipeline.config)
    risk_hints = _collect_risk_hints(
        normalized_text,
        source_type=pipeline.source_type,
        commands=commands,
        secret_findings=secret_findings,
        pipeline=pipeline.config,
    )
    deterministic_flags = _collect_flags(
        normalized_text,
        domains=domains,
        commands=commands,
        secret_findings=secret_findings,
        source_type=pipeline.source_type,
        pipeline=pipeline.config,
        truncation=truncation,
    )
    summary = _build_summary(
        source_type=pipeline.source_type,
        normalized_text=normalized_text,
        commands=commands,
        secret_findings=secret_findings,
        domains=domains,
    )
    artifact = {
        "artifact_id": _artifact_id(pipeline.source_type, source_ref, normalized_text),
        "source_type": pipeline.source_type,
        "source_ref": source_ref,
        "fetched_at": fetched_at,
        "pipeline": {
            "name": pipeline.source_type,
            "path": str(pipeline.path.relative_to(BASE_DIR)),
            "max_chars": pipeline.config.get("max_chars"),
            "max_lines": pipeline.config.get("max_lines"),
        },
        "normalized_text": normalized_text,
        "structured_fields": structured_fields,
        "domains": domains,
        "commands": commands,
        "secret_like_findings": secret_findings,
        "deterministic_flags": deterministic_flags,
        "risk_hints": risk_hints,
        "deterministic_summary": summary,
        "truncation": truncation,
        "next_stage_hint": {
            "default_consumer": "cheap-low-privilege-sanitizer",
            "escalate_if_any": [
                "prompt_injection_language",
                "contains_secret_like_string",
                "contains_executable_text",
                "git_metadata_is_untrusted",
                "ci_policy_surface",
            ],
        },
    }
    return artifact


def inspect_text(text: str, *, source_type: str, source_ref: str) -> dict[str, Any]:
    return inspect_payload({"text": text}, source_type=source_type, source_ref=source_ref)


def inspect_git_revision(
    repo: str | os.PathLike[str],
    revision: str = "HEAD",
    *,
    max_diff_bytes: int | None = None,
) -> dict[str, Any]:
    repo_path = Path(repo)
    pipeline = load_pipeline_config("git")
    if max_diff_bytes is None:
        max_diff_bytes = int(pipeline.config.get("git", {}).get("max_diff_bytes", 12000))
    show_format = "%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%s%x1f%b%x00"
    show_result = subprocess.run(
        ["git", "show", revision, f"--format=format:{show_format}", "--stat", "--summary", "--patch", "--no-ext-diff"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    raw_output = show_result.stdout
    header, separator, patch_body = raw_output.partition("\x00")
    if not separator:
        raise UntrustedIngestError(f"git show output for {revision} did not contain expected header separator")
    commit_sha, parents, author_name, author_email, authored_at, subject, body = header.split("\x1f")
    changed_paths = _git_changed_paths(repo_path, revision)
    payload = {
        "commit_sha": commit_sha,
        "parents": [item for item in parents.split() if item],
        "author_name": author_name,
        "author_email": author_email,
        "authored_at": authored_at,
        "subject": subject,
        "body": body.strip(),
        "changed_paths": changed_paths,
        "diff": patch_body[:max_diff_bytes],
        "diff_truncated": len(patch_body) > max_diff_bytes,
        "text": "\n".join(
            part
            for part in [
                f"commit {commit_sha}",
                f"author {author_name} <{author_email}>",
                f"date {authored_at}",
                f"subject {subject}",
                body.strip(),
                "changed_paths: " + ", ".join(changed_paths),
                patch_body[:max_diff_bytes],
            ]
            if part
        ),
    }
    artifact = inspect_payload(payload, source_type="git", source_ref=f"git:{revision}")
    artifact["structured_fields"].update(
        {
            "commit_sha": commit_sha,
            "parents": payload["parents"],
            "author_name": author_name,
            "author_email": author_email,
            "authored_at": authored_at,
            "subject": subject,
            "body": body.strip(),
            "changed_paths": changed_paths,
            "diff_truncated": payload["diff_truncated"],
        }
    )
    return artifact


def _git_changed_paths(repo_path: Path, revision: str) -> list[str]:
    result = subprocess.run(
        ["git", "show", "--pretty=", "--name-only", revision],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _project_payload(payload: Any, config: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, str):
        return {"text": payload}
    if not isinstance(payload, dict):
        return {"text": json.dumps(payload, sort_keys=True, ensure_ascii=False)}
    keep = config.get("field_allowlist")
    if keep:
        projected = {key: payload[key] for key in keep if key in payload}
        if "text" not in projected:
            projected["text"] = payload.get("text") or _flatten_unknown_payload(payload)
        return projected
    return dict(payload)


def _flatten_unknown_payload(payload: dict[str, Any]) -> str:
    pieces = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            pieces.append(f"{key}: {json.dumps(value, sort_keys=True, ensure_ascii=False)}")
        else:
            pieces.append(f"{key}: {value}")
    return "\n".join(pieces)


def _normalize_projected(projected: dict[str, Any], config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    text_parts: list[str] = []
    structured_fields: dict[str, Any] = {}
    for key, value in projected.items():
        if value is None:
            continue
        if key == "text":
            text_parts.append(_normalize_scalar(value))
            continue
        if isinstance(value, list):
            structured_fields[key] = [str(item) for item in value]
            text_parts.append(f"{key}: {', '.join(str(item) for item in value)}")
        elif isinstance(value, dict):
            structured_fields[key] = value
            text_parts.append(f"{key}: {json.dumps(value, sort_keys=True, ensure_ascii=False)}")
        else:
            structured_fields[key] = str(value)
            text_parts.append(f"{key}: {_normalize_scalar(value)}")
    text = "\n".join(part for part in text_parts if part).strip()
    text = _apply_regex_filters(text, config)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[\t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text).strip()
    return text, structured_fields


def _normalize_scalar(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _apply_regex_filters(text: str, config: dict[str, Any]) -> str:
    for item in config.get("regex_redactions", []):
        pattern = item["pattern"]
        replacement = item.get("replacement", "[redacted]")
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE | re.MULTILINE)
    return text


def _enforce_budget(text: str, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    max_lines = int(config.get("max_lines", 200))
    max_chars = int(config.get("max_chars", 12000))
    lines = text.splitlines()
    line_truncated = len(lines) > max_lines
    if line_truncated:
        text = "\n".join(lines[:max_lines]) + TRUNCATION_MARKER
    char_truncated = len(text) > max_chars
    if char_truncated:
        text = text[: max_chars - len(TRUNCATION_MARKER)].rstrip() + TRUNCATION_MARKER
    return text, {
        "was_truncated": bool(line_truncated or char_truncated),
        "line_truncated": line_truncated,
        "char_truncated": char_truncated,
        "original_lines": len(lines),
        "original_chars": len("\n".join(lines)),
        "normalized_chars": len(text),
    }


def _extract_domains(text: str) -> list[str]:
    domains = set()
    for url in URL_RE.findall(text):
        parsed = urlparse(url)
        if parsed.netloc:
            domains.add(parsed.netloc.lower())
    for domain in DOMAIN_RE.findall(text):
        lowered = domain.lower()
        if _looks_like_file_name(lowered):
            continue
        domains.add(lowered)
    return sorted(domains)


def _looks_like_file_name(token: str) -> bool:
    return token.endswith((
        ".sh",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".md",
        ".txt",
        ".cfg",
        ".ini",
        ".sql",
    ))


def _extract_commands(text: str, config: dict[str, Any]) -> list[str]:
    if not config.get("detect_commands", False):
        return []
    commands = []
    for match in COMMAND_RE.findall(text):
        cleaned = match.strip()
        if cleaned not in commands:
            commands.append(cleaned)
    return commands[:10]


def _detect_secret_like_patterns(text: str, config: dict[str, Any]) -> list[dict[str, str]]:
    if not config.get("detect_secret_patterns", False):
        return []
    findings = []
    for name, pattern in SECRET_PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            findings.append({"pattern": name, "sample": _redact_secret_sample(match.group(0))})
    return findings


def _redact_secret_sample(value: str) -> str:
    if len(value) <= 8:
        return "[redacted]"
    return value[:4] + "…" + value[-4:]


def _collect_risk_hints(
    text: str,
    *,
    source_type: str,
    commands: list[str],
    secret_findings: list[dict[str, str]],
    pipeline: dict[str, Any],
) -> list[str]:
    hints = ["untrusted_input"]
    if source_type in {"x", "web", "email", "discord", "log", "code", "git", "pipeline_config"}:
        hints.append(f"{source_type}_content_is_untrusted")
    if source_type == "git":
        hints.append("git_metadata_is_untrusted")
    if source_type in {"code", "pipeline_config", "git"}:
        hints.append("contains_executable_surface")
    if commands:
        hints.append("contains_executable_text")
    if secret_findings:
        hints.append("contains_secret_like_string")
    lower_text = text.lower()
    if any(token in lower_text for token in ["ignore previous instructions", "system prompt", "developer message", "send me your key"]):
        hints.append("prompt_injection_language")
    if source_type in {"pipeline_config", "git"} and any(
        needle in lower_text for needle in [".github/workflows", "workflow_run", "pull_request_target", "environmentfile=", "execstart="]
    ):
        hints.append("ci_policy_surface")
    if pipeline.get("high_risk_if_paths_match"):
        path_blob = lower_text
        if any(path.lower() in path_blob for path in pipeline["high_risk_if_paths_match"]):
            hints.append("high_risk_path_touched")
    return sorted(dict.fromkeys(hints))


def _collect_flags(
    text: str,
    *,
    domains: list[str],
    commands: list[str],
    secret_findings: list[dict[str, str]],
    source_type: str,
    pipeline: dict[str, Any],
    truncation: dict[str, Any],
) -> list[str]:
    flags = []
    if domains:
        flags.append("contains_domains")
    if commands:
        flags.append("contains_commands")
    if secret_findings:
        flags.append("contains_secret_like_pattern")
    if truncation.get("was_truncated"):
        flags.append("truncated")
    if source_type in {"git", "code", "pipeline_config"}:
        flags.append("code_or_config_surface")
    if source_type == "git":
        flags.append("git_metadata_treated_as_content")
    if pipeline.get("notes"):
        flags.extend(pipeline["notes"])
    return sorted(dict.fromkeys(flags))


def _build_summary(
    *,
    source_type: str,
    normalized_text: str,
    commands: list[str],
    secret_findings: list[dict[str, str]],
    domains: list[str],
) -> str:
    lead = normalized_text.splitlines()[0].strip() if normalized_text else ""
    lead = lead[:140]
    parts = [f"{source_type} artifact"]
    if lead:
        parts.append(f"lead={lead!r}")
    if domains:
        parts.append(f"domains={', '.join(domains[:3])}")
    if commands:
        parts.append(f"commands={len(commands)}")
    if secret_findings:
        parts.append(f"secret_like={len(secret_findings)}")
    return "; ".join(parts)


def _artifact_id(source_type: str, source_ref: str, normalized_text: str) -> str:
    digest = hashlib.sha256(f"{source_type}\n{source_ref}\n{normalized_text}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
