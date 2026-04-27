# swyx-to-Agent-Skills Pipeline Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a deterministic-first pipeline that ingests swyx content from X, YouTube, smol.ai, and the Latent Space podcast site, then drafts reviewed agent-skill candidates without letting raw hostile web/social content reach privileged agents by default.

**Architecture:** Source fetchers collect raw items into a local spool with provenance and hashes. Existing untrusted-ingestion reducers normalize each item, an isolated cheap-model sanitizer extracts agent-practice candidates, and a skill-drafting stage emits SKILL.md proposals into a review queue rather than auto-installing them.

**Tech Stack:** Python stdlib + existing `app.untrusted_ingest` / `app.codex_sanitizer`, `xurl` when configured for X, `youtube-transcript-api` helper for YouTube transcripts, feed/HTML parsers for websites, JSONL spool files, pytest.

**Bead:** `hermes-tailchat-u52`

---

## Acceptance criteria

- Fetchers cover swyx on X, YouTube, smol.ai, and Latent Space podcast website through source-specific adapters.
- All remote content is treated as untrusted and reduced before semantic extraction.
- Repeated content is deduplicated by stable content hash and source reference.
- Pipeline emits normalized artifacts, sanitizer outputs, candidate skill drafts, and review metadata as durable files.
- Candidate skills are not installed automatically; they require explicit human or sidecar review promotion.
- Tests cover source parsing, deduplication, hostile-content handling, skill draft schema validation, and dry-run CLI behavior.

## Proposed data flow

```text
source pollers
  -> raw spool: data/swyx/raw/YYYY-MM-DD/*.json
  -> deterministic reduction: app.untrusted_ingest
  -> sanitized extraction: app.codex_sanitizer / cheap model schema
  -> candidate model: agent-practice observations
  -> SKILL.md draft renderer
  -> review queue: data/swyx/candidates/*.json + drafts/*.md
  -> explicit promotion to ~/.hermes/skills or repo skills
```

## File layout

Create:
- `app/swyx_ingest/__init__.py`
- `app/swyx_ingest/sources.py`
- `app/swyx_ingest/spool.py`
- `app/swyx_ingest/extract.py`
- `app/swyx_ingest/skill_draft.py`
- `scripts/swyx_to_skills.py`
- `docs/specs/swyx-skill-candidate.schema.json`
- `docs/design/2026-04-27-swyx-to-agent-skills-pipeline.md`
- `tests/test_swyx_ingest.py`
- `tests/fixtures/swyx/`

Modify:
- `README.md` with operator usage once the CLI exists.
- Possibly `docs/design/2026-04-21-untrusted-ingestion-foundation.md` to link this as a concrete downstream pipeline.

## Source adapters

### X

- Preferred: `xurl search "from:swyx ..."` or user timeline if credentials/plan allow.
- Fallback: manual URL import mode for individual posts/threads.
- Raw fields to keep before reduction: id, author, created_at, text, urls, referenced_tweets, public_metrics, source_url.
- Never read or expose `~/.xurl`; only check `xurl auth status` during setup.

### YouTube

- Input options: channel URL, playlist URL, video URL, or manually curated URL list.
- Use the existing YouTube transcript helper pattern.
- Raw fields: video_id, title, published_at, channel, description, transcript segments with timestamps, source_url.
- If transcripts are disabled, record a skipped item with reason rather than failing the whole run.

### smol.ai

- Prefer RSS/Atom/sitemap if available; otherwise bounded HTML fetch.
- Raw fields: url, title, published_at if detected, author, canonical_url, extracted text, outbound links.
- Strip scripts/styles deterministically before reduction.

### Latent Space podcast website

- Prefer RSS feed for episodes and show notes.
- Pull transcript only if exposed as HTML/feed content; otherwise record metadata and show notes.
- Raw fields: episode url, title, date, guests, description/show notes, transcript text if present, media url.

## Candidate extraction schema

Each sanitizer output should produce zero or more candidate observations:

```json
{
  "source_refs": ["youtube:VIDEO_ID", "x:POST_ID"],
  "claim": "A reusable agent workflow or tool pattern in one sentence.",
  "evidence": [
    {"source_ref": "youtube:VIDEO_ID", "quote": "bounded quote", "timestamp": "00:12:34"}
  ],
  "skill_trigger": "Use when ...",
  "workflow_steps": ["step one", "step two"],
  "tooling": ["tool names or APIs mentioned"],
  "risk_notes": ["prompt injection", "requires external credentials"],
  "confidence": "low|medium|high",
  "proposed_skill_name": "lowercase-hyphen-name"
}
```

## Promotion rules

- `low` confidence: keep as research note only.
- `medium` confidence: create candidate draft with TODO markers and require review.
- `high` confidence with multiple evidence refs: create a complete SKILL.md draft in `data/swyx/drafts/`.
- Never auto-write into `~/.hermes/skills/` or `skills/` without explicit promotion command.
- Promotion command validates frontmatter, description length, body presence, and evidence links.

---

## Task 1: Add candidate schema

**Objective:** Define the machine-checkable contract for extracted candidate skills.

**Files:**
- Create: `docs/specs/swyx-skill-candidate.schema.json`
- Test: `tests/test_swyx_ingest.py`

**Steps:**
1. Add JSON Schema for the candidate object above.
2. Write a fixture candidate that validates.
3. Write a fixture missing `source_refs` that fails validation.
4. Run: `pytest -q tests/test_swyx_ingest.py`.
5. Commit with `Refs: hermes-tailchat-u52`.

## Task 2: Add spool primitives

**Objective:** Store raw, normalized, sanitized, and candidate artifacts with stable hashes.

**Files:**
- Create: `app/swyx_ingest/spool.py`
- Test: `tests/test_swyx_ingest.py`

**Steps:**
1. Implement `content_hash(payload: Mapping) -> str` using canonical JSON.
2. Implement `spool_path(root, stage, source_type, source_ref, payload)`.
3. Implement atomic write for JSON artifacts.
4. Test that identical payloads produce identical paths and changed payloads do not.
5. Run: `pytest -q tests/test_swyx_ingest.py`.
6. Commit with `Refs: hermes-tailchat-u52`.

## Task 3: Add source models and manual import

**Objective:** Establish normalized internal source item structures before live fetching.

**Files:**
- Create: `app/swyx_ingest/sources.py`
- Modify: `scripts/swyx_to_skills.py`
- Test: `tests/test_swyx_ingest.py`

**Steps:**
1. Define a `SourceItem` dataclass with `source_type`, `source_ref`, `source_url`, `raw_fields`, `fetched_at`.
2. Add `manual-json` CLI mode that reads a local JSON file containing items.
3. Spool those items to `data/swyx/raw/` in dry-run-friendly mode.
4. Test manual JSON import without network.
5. Run: `pytest -q tests/test_swyx_ingest.py`.
6. Commit with `Refs: hermes-tailchat-u52`.

## Task 4: Wire deterministic reduction

**Objective:** Reuse existing untrusted-ingestion primitives as the trust boundary.

**Files:**
- Create: `app/swyx_ingest/extract.py`
- Modify: `scripts/swyx_to_skills.py`
- Test: `tests/test_swyx_ingest.py`

**Steps:**
1. Convert `SourceItem.raw_fields` into the existing untrusted-ingestion JSON path.
2. Use source types `x`, `web`, and a new logical wrapper for YouTube/podcast as web text if no dedicated profile exists.
3. Spool normalized artifacts separately from raw items.
4. Test that prompt-injection text in fixtures is flagged as untrusted/prompt-injection-like.
5. Run: `pytest -q tests/test_swyx_ingest.py tests/test_untrusted_ingest.py`.
6. Commit with `Refs: hermes-tailchat-u52`.

## Task 5: Add website/feed fetchers

**Objective:** Fetch smol.ai and Latent Space items from feeds or bounded HTML.

**Files:**
- Modify: `app/swyx_ingest/sources.py`
- Test: `tests/test_swyx_ingest.py`
- Fixtures: `tests/fixtures/swyx/smol_feed.xml`, `tests/fixtures/swyx/latent_space_feed.xml`

**Steps:**
1. Implement parser functions that accept feed/HTML text and return `SourceItem` values.
2. Keep network I/O thin and separately testable from parsing.
3. Add parser fixtures for feed entries with titles, dates, URLs, and summaries.
4. Test parser behavior and truncation.
5. Run: `pytest -q tests/test_swyx_ingest.py`.
6. Commit with `Refs: hermes-tailchat-u52`.

## Task 6: Add YouTube transcript adapter

**Objective:** Import transcripts for configured videos/channel items without making transcript failure fatal.

**Files:**
- Modify: `app/swyx_ingest/sources.py`
- Modify: `scripts/swyx_to_skills.py`
- Test: `tests/test_swyx_ingest.py`

**Steps:**
1. Add URL/video-id normalization.
2. Add adapter interface that can be backed by the existing `youtube-transcript-api` helper.
3. Represent transcript-disabled/private videos as skipped records with a reason.
4. Test URL normalization and skipped-record behavior using fixtures/mocks.
5. Run: `pytest -q tests/test_swyx_ingest.py`.
6. Commit with `Refs: hermes-tailchat-u52`.

## Task 7: Add X adapter behind capability check

**Objective:** Support X ingestion when `xurl` is installed and authenticated, while preserving manual fallback.

**Files:**
- Modify: `app/swyx_ingest/sources.py`
- Modify: `scripts/swyx_to_skills.py`
- Test: `tests/test_swyx_ingest.py`

**Steps:**
1. Add `xurl auth status` capability check; do not read credential files.
2. Add parser for JSON returned by `xurl search` / `xurl read`.
3. Add CLI option for `--x-query` and `--x-url` dry-run imports.
4. Test parser against fixture JSON.
5. Run: `pytest -q tests/test_swyx_ingest.py`.
6. Commit with `Refs: hermes-tailchat-u52`.

## Task 8: Add skill-draft renderer

**Objective:** Turn reviewed candidate observations into SKILL.md draft files.

**Files:**
- Create: `app/swyx_ingest/skill_draft.py`
- Test: `tests/test_swyx_ingest.py`

**Steps:**
1. Implement proposed skill name sanitization.
2. Render Hermes-style frontmatter and body sections: Overview, When to Use, Workflow, Evidence, Pitfalls, Verification.
3. Include evidence references but not huge raw quotes.
4. Validate frontmatter constraints from the skill authoring rules.
5. Run: `pytest -q tests/test_swyx_ingest.py`.
6. Commit with `Refs: hermes-tailchat-u52`.

## Task 9: Add sanitizer-backed extraction command

**Objective:** Use isolated low-privilege model extraction to produce candidate observations.

**Files:**
- Modify: `app/swyx_ingest/extract.py`
- Modify: `scripts/swyx_to_skills.py`
- Test: `tests/test_swyx_ingest.py`

**Steps:**
1. Define a prompt that treats normalized artifacts as hostile data, not instructions.
2. Use schema-bound output for candidate observations.
3. Keep a `--no-model` mode that only performs fetch/reduce/spool.
4. Test no-model path and mock sanitizer path.
5. Run: `pytest -q tests/test_swyx_ingest.py tests/test_untrusted_ingest.py`.
6. Commit with `Refs: hermes-tailchat-u52`.

## Task 10: Document and add operator recipe

**Objective:** Make the pipeline usable without Discord/chat history.

**Files:**
- Create: `docs/design/2026-04-27-swyx-to-agent-skills-pipeline.md`
- Modify: `README.md`

**Steps:**
1. Document source configuration, dry-run usage, trust boundary, and promotion rules.
2. Add examples for manual URL import, no-model reduction, and model-backed candidate extraction.
3. Add security notes for X credentials and website hostile content.
4. Run: `python -m py_compile app/*.py app/swyx_ingest/*.py scripts/*.py` and relevant pytest commands.
5. Commit with `Refs: hermes-tailchat-u52`.

## Final verification

Run:

```bash
python -m py_compile app/*.py app/swyx_ingest/*.py scripts/*.py
pytest -q tests/test_swyx_ingest.py tests/test_untrusted_ingest.py
python3 scripts/swyx_to_skills.py --help
python3 scripts/swyx_to_skills.py manual-json --file tests/fixtures/swyx/manual_items.json --dry-run --no-model
```

Expected:
- tests pass
- dry-run writes no promotion-side effects
- raw artifacts remain separate from normalized/sanitized/candidate artifacts
- candidate drafts are review artifacts, not installed skills
