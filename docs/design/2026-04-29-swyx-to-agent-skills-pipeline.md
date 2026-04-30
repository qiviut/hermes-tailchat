# swyx-to-agent-skills pipeline design

Date: 2026-04-29
Bead: hermes-tailchat-u52

## Purpose

Collect swyx-related public content into a deterministic local review pipeline that can propose reusable agent-skill candidates without letting raw external content become future instructions by default.

## Trust boundary

All source content is treated as hostile input:

1. Source adapters create `SourceItem` records with provenance.
2. Raw records are written to ignored local spool storage under `data/swyx/raw/`.
3. `app.swyx_ingest.extract` projects source-specific fields and calls `app.untrusted_ingest.inspect_payload`.
4. Normalized artifacts are written separately under `data/swyx/normalized/`.
5. Skill candidates and drafts remain review artifacts. They are never installed into `~/.hermes/skills/` or repo skills automatically.

## First slice

This slice intentionally ships the local deterministic core before broad live fetching:

- candidate JSON schema
- stable content hashing and atomic spool writes
- manual JSON import for curated/offline items
- xurl JSON parsing and bounded `--x-query` dry-run support
- reducer wiring to the existing untrusted-ingestion toolkit
- review-required SKILL.md draft rendering and CLI review-queue writes from candidate JSON

## Operator notes

`xurl` is optional for tests. When available, the CLI uses normal xurl auth state and never reads or prints `~/.xurl`.

Run artifacts under `data/swyx/` are ignored because raw X/web content can contain hostile text and should not be committed accidentally.
