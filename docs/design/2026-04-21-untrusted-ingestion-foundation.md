# Untrusted ingestion foundation

Date: 2026-04-21  
Bead: `hermes-tailchat-lqx`

## Why this exists

Hermes Tailchat increasingly touches hostile or semi-hostile text sources: websites, email, Discord, X, logs, source code, scripts, pipeline configs, and git metadata. Those inputs can carry prompt injection, social engineering, executable snippets, or secret-shaped bait. They should not flow raw into higher-authority agents.

This foundation adds a deterministic first pass that:

1. classifies source families as untrusted by default
2. projects only a bounded allowlist of fields per source type
3. normalizes noisy text into a compact artifact
4. extracts obvious high-signal indicators such as domains, commands, and secret-like strings
5. emits a stable normalized record that a cheaper low-privilege sanitizer model or future privileged consumer can inspect

## Scope of this first slice

Implemented now:
- source profiles for `code`, `pipeline_config`, `git`, `web`, `email`, `discord`, `log`, and `x`
- deterministic field projection and budget caps
- regex-based reduction hooks stored in versioned JSON pipeline configs
- command extraction, domain extraction, secret-like pattern detection, and risk hints
- git commit inspection covering commit message, body, changed paths, and bounded diff text
- a CLI at `scripts/untrusted_ingest.py`
- an isolated Codex sanitizer worker at `app/codex_sanitizer.py`
- a Codex sanitizer CLI at `scripts/untrusted_codex_sanitize.py`
- a schema-bound sanitizer contract at `docs/specs/untrusted-sanitizer-output.schema.json`
- tests proving that code comments, scripts, pipeline configs, git metadata, and the Codex sanitizer path are treated as untrusted input

Not implemented yet:
- verifier/second-model stage
- queueing/caching/spool storage
- integration into background workers or web routes

## Trust boundary

The intended flow is:

1. fetch raw content in a low-privilege fetcher
2. run deterministic reduction with this toolkit
3. hand the normalized artifact to a cheap low-privilege sanitizer model if semantic classification is needed
4. only then pass a sanitized summary onward to stronger or more privileged agents

The current default model-backed sanitizer worker is Codex, but only in an explicitly restricted mode:
- isolated temporary workspace containing only the normalized artifact and schema/prompt files
- `codex exec --sandbox read-only --skip-git-repo-check --ephemeral --ignore-user-config`
- minimal inherited environment containing only Codex/OpenAI auth plus basic process/runtime variables
- explicit `--model` selection so high-volume filters can use cheaper model tiers

The raw hostile blob should not be the default input for a secret-bearing or tool-rich agent.

## Operator usage

Inspect arbitrary text:

```bash
python3 scripts/untrusted_ingest.py text --source-type email --source-ref message:123 < suspicious.txt
```

Inspect JSON payloads:

```bash
python3 scripts/untrusted_ingest.py json --source-type x --source-ref tweet:123 --file sample.json
```

Inspect git metadata and diff:

```bash
python3 scripts/untrusted_ingest.py git --repo . --revision HEAD
```

Inspect then sanitize through isolated Codex:

```bash
python3 scripts/untrusted_codex_sanitize.py --model gpt-5-mini text --source-type email --source-ref message:123 < suspicious.txt
python3 scripts/untrusted_codex_sanitize.py --model gpt-5-mini git --repo . --revision HEAD
```

## Why JSON configs

This repo wants curated pipelines over time, but not a new ad hoc script for every source. Versioned JSON configs let us keep the stable code primitives small while tuning:
- field allowlists
- byte/line budgets
- redaction patterns
- high-risk path markers
- source aliases

That makes future polishing cheap enough to be worth doing.

## Expected next steps

- add a schema-bound cheap-model sanitizer stage that consumes these normalized records
- cache artifacts by content hash to reduce repeated work
- wire the toolkit into background review workers so remote/web/chat content is reduced before higher-authority analysis
- expand path- and authority-aware rules for CI, deploy, and secret-handling surfaces
