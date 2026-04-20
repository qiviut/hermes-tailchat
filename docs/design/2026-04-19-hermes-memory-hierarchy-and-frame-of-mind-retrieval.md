# Hermes memory hierarchy and frame-of-mind retrieval design

Date: 2026-04-19
Bead: `hermes-tailchat-des`
Status: proposed design / implementation backlog defined

## Goal

Define a maintainable memory architecture for Hermes Tailchat that:

- treats official Hermes primitives as the base layer
- keeps always-injected memory intentionally small
- uses skills as warm procedural frames rather than factual dumping grounds
- stores larger episodic and telemetry artifacts cold
- retrieves the smallest useful context for the current mode of work
- supports background "dreaming" and later AI-assisted maintenance without requiring an invasive Hermes-core fork first

## Non-goals

This design does not:

- expand `USER.md` or `MEMORY.md` beyond their intended role as bounded hot memory
- require a first-class Hermes upstream feature before local progress is possible
- assume every useful artifact must be injected into every turn
- treat dreams, logs, skills, and memories as one undifferentiated store
- require autonomous edits to memory or skills without reviewable evidence

---

## Recommendation in one paragraph

Use a three-layer memory hierarchy on top of existing Hermes features. Keep hot memory limited to durable, high-signal facts in built-in `USER.md` and `MEMORY.md`. Treat skills, context files, and a small set of mode-specific retrieval manifests as warm memory that provides procedural frames and stable guidance on demand. Store transcripts, dream windows, analysis candidates, overlay reports, and future searchable archives as cold memory that is fetched selectively through deterministic tooling and explicit retrieval policy. Add a repo-local frame-of-mind router that chooses among coding, operator, reflection, and conversational modes, then loads only the smallest useful hot/warm/cold bundle for that mode. Use cron plus deterministic dream artifacts to audit what is overused, stale, contradictory, or missing, and only then invite AI judgment for compression, promotion, demotion, or skill repair.

---

## Problem framing

Official Hermes already gives us most of the pieces:

- built-in bounded memory
- external memory providers
- skills
- context files
- context references
- cron
- hooks

What it does not yet give us is an explicit local policy answering questions like:

- what must stay hot?
- what belongs in skills instead of memory?
- what should move cold into dream artifacts or searchable storage?
- which retrieval bundle fits a coding task versus a reflective maintenance task?
- how do we gather enough evidence to improve memory and skills instead of editing them blindly?

This design answers those policy questions without trying to replace Hermes itself.

---

## Design principles

1. Hot memory is scarce and should behave like RAM.
2. Procedural guidance and factual memory are different objects and should stay distinct.
3. Cold storage should be cheap to accumulate but expensive to inject by default.
4. Retrieval should be mode-sensitive and evidence-first.
5. Deterministic preprocessing should happen before AI judgment.
6. Provenance matters: every proposed memory or skill change should be traceable to transcript windows, usage counts, or other concrete artifacts.
7. Local layering should minimize upstream conflict by preferring hooks, cron, files, and skills over Hermes-core patching.

---

## The hierarchy

### Layer 1: hot memory

Primary substrate:

- Hermes built-in `USER.md`
- Hermes built-in `MEMORY.md`

Role:

- always-injected, high-signal, low-volume context
- durable preferences, standing corrections, stable environment facts, and facts that repeatedly save steering effort

Keep hot only when a fact passes this test:

- it is durable
- it is broadly useful across many future sessions
- not having it hot would likely cause repeated mistakes or repeated user steering

Examples that belong hot:

- user preferences about risk tolerance, velocity, auth posture, or command approval style
- stable environment facts such as where a repo usually lives or how a specific machine is exposed
- repeated corrections like "do not run bare bv"

Examples that should not remain hot:

- session-specific progress notes
- long architectural rationales
- rarely used commands
- raw logs or transcript excerpts
- implementation detail that only matters in one repo or mode and can be retrieved on demand

Why:

- hot memory is frozen at session start and has a hard size ceiling
- overfilling it degrades signal and increases context tax on every conversation

### Layer 2: warm memory

Primary substrate:

- Hermes skills
- project context files such as `AGENTS.md`
- small mode-specific retrieval manifests stored in this repo
- future warm indexes derived from deterministic dream artifacts

Role:

- selectively loaded procedural and frame-setting guidance
- stable but non-universal context
- mode-specific operator posture that is too large or specialized for hot memory

Warm memory splits into two subtypes.

#### 2a. Procedural warm memory

Examples:

- skills for beads workflow, architecture review, testing, deployment, or dreaming
- repo guidance in `AGENTS.md`
- reusable validation/checklist flows

Why:

- these encode how to work, not facts about the user
- they should be loaded when relevant and omitted when not

#### 2b. Frame warm memory

Examples:

- a coding frame manifest emphasizing codebase inspection, tests, acceptance criteria, and minimal necessary project docs
- an operator frame manifest emphasizing service state, timers, logs, deploy drift, and risk containment
- a reflection frame manifest emphasizing transcript windows, skill/memory churn, contradictions, and maintenance proposals
- a conversational frame manifest emphasizing concise continuity, user goals, and low-overhead retrieval

Why:

- current Hermes skills are the closest official carrier for reusable modes of thought
- frame manifests can start as files plus skills, then later become generated indexes if justified

### Layer 3: cold memory

Primary substrate:

- dream artifacts under `~/.local/state/hermes-tailchat/dreaming/`
- exported Hermes sessions
- transcript windows and analysis candidates
- overlay reports and patch exports
- external memory providers or searchable file stores for larger archives
- repo docs/research notes and other fetchable artifacts

Role:

- large, selective, evidence-bearing storage
- episodic history, telemetry, and provenance
- source material for later retrieval, compression, and maintenance

Examples that belong cold:

- `windows.json`
- `analysis-candidates.json`
- `runs.jsonl`
- exported session transcripts
- long research and design notes
- future skill-usage rollups and contradiction reports
- future searchable artifacts derived from hooks or provider-backed memory

Why:

- cold artifacts should be rich and durable, but not automatically injected
- their job is to support selective retrieval and maintenance, not to bloat every turn

---

## Data placement policy

### Keep hot

Keep in built-in memory only:

- stable user preferences
- stable environment facts
- repeated corrections and conventions
- compact facts with high reuse across modes

### Keep warm

Keep in skills or frame manifests:

- procedures
- checklists
- mode-specific heuristics
- repo-local guidance
- structured retrieval hints for common task classes

### Move cold

Move into dream artifacts, docs, or searchable storage:

- detailed evidence explaining why a memory or skill should change
- transcript windows
- session export data
- usage frequency reports
- longer architectural or operational notes
- per-run diagnostics and overlay maintenance artifacts

### Remove entirely

Remove or avoid storing when information is:

- temporary and no longer useful
- duplicated elsewhere with a better source of truth
- too narrow for hot memory and too weak to justify warm or cold retention
- contradicted or stale without an active reason to preserve it for history

---

## Frame-of-mind retrieval model

The retrieval router should classify work into one primary mode, optionally with one secondary mode.

Initial supported modes:

1. coding
2. operator
3. reflection
4. conversational

If a task crosses modes, prefer one dominant mode and add at most one secondary frame rather than loading everything.

### Coding mode

Use when:

- implementing features
- debugging
- reviewing code
- writing tests
- navigating repo architecture

Primary retrieval policy:

- hot memory as normal
- relevant repo context files and coding-related skills
- small slice of bead/task context
- code/docs fetched on demand through file search/read
- avoid loading dream artifacts unless the task is specifically about memory/skill maintenance or prior failures

Preferred warm bundle:

- repo `AGENTS.md`
- relevant engineering skills
- small task-specific plan/design artifact

Preferred cold bundle:

- specific files, diffs, or previous research notes only when directly relevant

Main risk if over-expanded:

- coding turns become clogged with operator and reflection baggage

### Operator mode

Use when:

- checking service health
- deploy/restart/rollback work
- systemd/timer state
- local overlay and environment maintenance
- infrastructure or tailnet exposure questions

Primary retrieval policy:

- hot memory as normal
- operator guidance from context files/skills
- recent state reports, service docs, and local deployment conventions
- cold retrieval from overlay report, dream summary, service status, and relevant logs

Preferred warm bundle:

- operator frame manifest
- relevant deployment/systemd/repo guidance

Preferred cold bundle:

- latest-summary.json
- overlay-report.json
- runs.jsonl excerpts
- service-specific docs or logs

Main risk if over-expanded:

- operator work gets buried under irrelevant coding or reflective context

### Reflection mode

Use when:

- auditing memories or skills
- deciding compression/promote/demote/remove actions
- designing or evaluating dreaming improvements
- reviewing repeated failures or frequent-skill hotspots

Primary retrieval policy:

- hot memory only as compact background, not the main evidence source
- warm retrieval of dreaming and memory-architecture guidance
- cold retrieval is the default evidence plane: transcript windows, analysis candidates, skill frequency counts, memory action counts, session recall evidence, and patch/overlay signals

Preferred warm bundle:

- dreaming toolkit design
- memory hierarchy design
- any memory/skills maintenance skill

Preferred cold bundle:

- `windows.json`
- `analysis-candidates.json`
- `latest-summary.json`
- targeted session exports
- future contradiction/staleness reports

Main risk if over-expanded:

- reflection becomes vague philosophy instead of evidence-backed maintenance

### Conversational mode

Use when:

- answering broad user questions
- discussing product direction
- offering recommendations without immediate implementation
- quick continuity questions

Primary retrieval policy:

- prefer hot memory and a narrow warm bundle
- only pull cold evidence when the answer depends on current facts, prior transcript details, or concrete design artifacts
- optimize for low context tax and quick interaction

Preferred warm bundle:

- only directly relevant skills or docs

Preferred cold bundle:

- one or two specific artifacts if needed for grounding

Main risk if over-expanded:

- simple discussion becomes sluggish and over-instrumented

---

## Retrieval algorithm

The local router does not need to be fancy at first. A simple staged policy is enough.

### Stage 0: baseline

Always present:

- hot built-in memory
- ambient project context files already discovered by Hermes

### Stage 1: classify mode

Classify the task into one primary mode using deterministic cues first:

- coding words: implement, fix, refactor, test, review, diff, bug
- operator words: restart, deploy, service, timer, status, logs, tailscale, systemd
- reflection words: memory, skill, dream, audit, compress, improve, stale, contradiction, retrieval
- conversational words: explain, compare, should, does Hermes support, what do you think

If uncertain, default to conversational for low-stakes discussion and coding/operator for clearly tool-driven work.

### Stage 2: load warm frame

Load only:

- the most relevant skill(s)
- any mode manifest or repo guidance required for safe work
- one small design/research artifact if the task directly depends on it

### Stage 3: fetch cold evidence on demand

Pull the smallest useful artifact set.

Examples:

- reflection on memory maintenance -> top candidate windows plus summary stats, not all sessions
- operator check -> latest summary and current service status, not all logs
- coding task -> the exact files and task design, not dreaming artifacts

### Stage 4: evaluate need to escalate retrieval

Escalate only if the current bundle is insufficient.

Escalation order:

1. one more specific file or artifact
2. one more skill or context file
3. one session-level bundle
4. broader cold search or provider search

This is meant to preserve low context tax.

---

## Dreaming and maintenance loop

The dreaming subsystem should remain a background maintenance loop, not a hidden always-on prompt mutation system.

### Deterministic phase

Current or near-term deterministic artifacts provide:

- skill usage counts
- memory action counts
- signal-dense sessions
- transcript windows around `skill_view`, `skill_manage`, `memory`, and `session_search`
- ranked analysis candidates
- overlay drift and patch state

### Judgment phase

AI analysis should answer questions like:

- did this skill help or repeatedly fail in context?
- is a hot-memory item earning its rent?
- should a repeated pattern become a skill instead of a memory note?
- should some hot memory be compressed, moved warm, moved cold, or removed?
- does a frequently used skill need patching, splitting, or a more mode-specific companion?

### Action phase

Actions should remain explicit and reviewable:

- hot memory: keep, compress, move, remove
- skills: keep, patch, split, create companion frame, retire
- cold artifacts: retain, summarize, index, or prune according to retention policy

This keeps deterministic evidence and human-reviewable judgment separate.

---

## Rent, utility, and overuse signals

The system should treat skill and memory frequency as a signal, not a verdict.

### When high frequency is good

- a skill is repeatedly useful because it captures a core workflow
- a memory entry prevents repeated mistakes
- a frame manifest is doing real work in the right mode

### When high frequency is suspicious

- a skill is doing work that should have been distilled into hot memory or repo guidance
- a large skill is being loaded for many unrelated situations and should be split
- an operational pattern is repeatedly reconstructed from scratch because it lacks a better frame manifest
- repeated `memory replace` churn suggests a hot-memory item is unstable and should not be hot

### When low frequency matters

Low frequency is not automatically bad. Some artifacts are high value but situational.

Bad low-frequency patterns are things like:

- a skill that exists because of repeated failures but is never loaded when those failures recur
- an important operator frame that is absent from operator tasks
- a useful research note that is never referenced because retrieval is too hard or too implicit

---

## Provenance and evidence model

Every proposed maintenance action should be traceable to one or more of:

- a transcript window
- a dream summary usage stat
- a session-search event
- a skill patch or memory churn event
- a concrete operator artifact such as overlay or deploy drift

Preferred evidence bundle format:

- reason for review
- mode
- candidate artifact paths
- relevant usage counts
- one or more transcript windows
- recommended action
- confidence and caveats

This reduces hand-wavy memory editing.

---

## Local implementation shape

### Files and artifacts

This design assumes the following local surfaces.

Hot:

- Hermes built-in user and memory stores

Warm:

- `AGENTS.md`
- selected skills
- this design doc
- dreaming toolkit design doc
- future mode manifests, likely under a repo-local `docs/design/` or `config/` path

Cold:

- `~/.local/state/hermes-tailchat/dreaming/latest-summary.json`
- `~/.local/state/hermes-tailchat/dreaming/windows.json`
- `~/.local/state/hermes-tailchat/dreaming/analysis-candidates.json`
- `~/.local/state/hermes-tailchat/dreaming/runs.jsonl`
- `~/.local/state/hermes-tailchat/dreaming/overlay-report.json`
- exported sessions and future searchable stores

### Suggested new local concepts

1. Mode manifest
   - a small declarative description of what warm/cold sources to prefer for each mode
2. Retrieval bundle
   - a concrete selected artifact set for one task/run
3. Memory audit decision record
   - a deterministic-plus-judgment summary that says keep/compress/move/remove
4. Skill audit decision record
   - evidence-backed keep/patch/split/retire recommendation

These can begin as plain files and JSON artifacts before any richer UI or index exists.

---

## Promotion and demotion policy

### Promote to hot only when

- the fact is stable
- cross-mode usefulness is high
- the content is short enough to be worth permanent injection
- omission would likely cause repeated steering or repeated mistakes

### Promote to warm when

- the content is procedural or mode-specific
- it is too large or specialized for hot memory
- it should be available on demand without requiring full cold search every time

### Demote from hot when

- it changes too often
- it is only useful in one narrow mode
- it can be represented better in a skill, context file, or cold artifact
- it no longer earns its context rent

### Demote from warm when

- the artifact is stale and no longer used
- the content is mostly historical evidence rather than live guidance
- retrieval is better served by cold search plus a small summary

---

## Risks and tradeoffs

### Main benefits

- lower context tax in ordinary sessions
- clearer distinction between facts, procedures, and evidence
- maintainable path to dreaming without a large Hermes fork
- better evidence for improving skills and memories
- easier future upstream conversation because the design is expressed in official Hermes terms

### Main risks

- mode classification may be wrong for mixed tasks
- too many manifests or indexes could recreate the bloat we are trying to avoid
- aggressive maintenance could churn memories or skills without enough stability
- cold retrieval can become cumbersome if artifacts are not well indexed

### Mitigations

- keep initial mode set small
- prefer one primary mode plus at most one secondary mode
- require evidence bundles before non-trivial memory or skill changes
- build deterministic indexes before AI-heavy automation
- bias toward explicit retrieval over hidden prompt accretion

---

## Upstreamability view

This design stays close to official Hermes primitives.

Repo-local now:

- mode manifests
- deterministic dream artifacts
- retrieval policy
- maintenance scoring and evidence bundles

Potential future upstream candidates:

- first-class frame-of-mind routing
- context-rent/utility accounting for hot memory and skills
- memory/skill maintenance reports derived from session history
- better official support for mode-specific retrieval bundles

This means local work can proceed now while preserving a sensible path to later upstream discussion.

---

## Mapping to dependent beads

### `hermes-tailchat-add`

Implement deterministic audit/compression tooling for hot memory using this policy:

- classify entries as keep-hot, compress, move, remove
- use dream artifacts and usage evidence to support recommendations
- avoid quota-chasing; optimize for signal

### `hermes-tailchat-pro`

Prototype the frame-of-mind retrieval index:

- encode the initial four modes
- map each mode to preferred warm/cold sources
- output minimal retrieval bundles for a task

### `hermes-tailchat-doc`

Align README/docs with the hierarchy:

- explain hot/warm/cold concepts
- document mode-sensitive retrieval
- connect dreaming artifacts to maintenance, not just collection

### `hermes-tailchat-rev`

Review this design for official-Hermes fit and upstreamability:

- ensure we are using hooks, cron, skills, files, and providers in the least invasive order
- identify any places where a local layer is pretending to be an official feature

---

## Acceptance checklist

This design now defines:

- hot, warm, and cold layers
- what belongs in each layer and why
- retrieval modes for coding, operator, reflection, and conversational work
- a mode-guided retrieval algorithm
- a deterministic-plus-judgment dreaming loop for maintenance
- a low-conflict local implementation path aligned with official Hermes primitives

---

## Recommended next step

Implement the retrieval-index prototype and memory-audit tooling as separate follow-on slices.

The key discipline for those slices should be:

- deterministic artifact generation first
- explicit evidence bundles second
- AI judgment third
- durable memory/skill edits last

That order keeps the memory hierarchy practical, reviewable, and cheap to maintain.
