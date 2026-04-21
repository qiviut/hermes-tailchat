# Untrusted Ingestion Foundation Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add an initial deterministic-first ingestion toolkit that normalizes hostile input into a constrained artifact before any higher-authority agent consumes it.

**Architecture:** Keep the first slice local and deterministic: a small Python module in `app/` owns schemas, reduction logic, and config loading; a thin CLI in `scripts/` exposes the pipeline for `json`, `text`, and `git` inputs; docs/specs capture the trust boundary and artifact format. The sanitizer/model stages remain configuration-ready and represented in the output schema, but the shipped code only performs the raw-fetch and deterministic reduction stages so it is immediately useful and cheap.

**Tech Stack:** Python 3.11+, stdlib, existing FastAPI repo test stack, JSON pipeline configs.

---

### Task 1: Define schemas and source profiles

**Objective:** Create explicit artifact and pipeline schemas plus source profiles that classify code, scripts, pipeline configs, git metadata, web, chat, email, logs, and X as untrusted.

**Files:**
- Create: `docs/specs/untrusted-ingestion-record.schema.json`
- Create: `docs/specs/untrusted-ingestion-pipeline.schema.json`
- Create: `config/untrusted_ingest/pipelines/*.json`

**Verification:** Load each config in tests and assert the source-specific rules are present.

### Task 2: Implement deterministic reduction library

**Objective:** Add a reusable Python module that projects fields, normalizes text, strips or summarizes noisy structures, extracts high-signal metadata, and emits a bounded normalized artifact.

**Files:**
- Create: `app/untrusted_ingest.py`

**Verification:** Unit tests cover truncation, URL/domain extraction, command extraction, secret-like token detection, and source-specific flags for git/code/config inputs.

### Task 3: Add a thin CLI for operators and future workers

**Objective:** Provide a repo-local CLI that can inspect JSON/text payloads or a git commit/range using the deterministic ingestion library.

**Files:**
- Create: `scripts/untrusted_ingest.py`

**Verification:** CLI smoke tests run against fixture input and a temporary git repo.

### Task 4: Add tests and operator docs

**Objective:** Document the trust model and make the new toolkit regression-tested.

**Files:**
- Create: `tests/test_untrusted_ingest.py`
- Create: `docs/design/2026-04-21-untrusted-ingestion-foundation.md`
- Modify: `README.md`

**Verification:** `pytest -q tests/test_untrusted_ingest.py` passes and docs explain that raw hostile content should not flow directly into privileged agents.
