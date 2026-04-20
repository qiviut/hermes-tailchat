# Review: Hermes memory hierarchy plan for official fit and upstreamability

Date: 2026-04-20
Bead: `hermes-tailchat-rev`
Status: interim review, not final closure

## Scope reviewed

Artifacts reviewed together:

- `docs/research/2026-04-19-hermes-memory-hierarchy-primitives.md`
- `docs/design/2026-04-18-hermes-dreaming-toolkit.md`
- `docs/design/2026-04-19-hermes-memory-hierarchy-and-frame-of-mind-retrieval.md`
- `app/dreaming.py`
- `scripts/hermes_dream.py`
- `README.md`

Open dependency state at review time:

- `hermes-tailchat-tn2` — closed
- `hermes-tailchat-des` — closed
- `hermes-tailchat-pro` — closed
- `hermes-tailchat-doc` — closed during this pass
- `hermes-tailchat-add` — still open

Because `hermes-tailchat-add` is still open, this review is architectural/interim rather than the final closure review for the whole hierarchy program.

## Verdict

Interim-positive.

The current memory-hierarchy and dreaming work fits official Hermes well because it composes documented Hermes primitives instead of pretending an upstream core subsystem already exists. The local implementation is mostly low-conflict orchestration over built-in memory, skills, context files/references, cron-like background collection, and file-based artifacts.

The plan is maintainable enough to continue, but it is not yet complete enough for final sign-off. The main remaining gap is the still-open hot-memory audit/compression tooling (`hermes-tailchat-add`), which is the key practical mechanism for validating the hot/warm/cold policy against real `USER.md` and `MEMORY.md` contents.

## Strong fits with official Hermes

### 1. Hot memory is modeled correctly

The design treats built-in `USER.md` and `MEMORY.md` as small always-injected memory with real size pressure rather than as a large archive.

That matches official Hermes behavior:

- bounded memory stores
- frozen snapshot at session start
- explicit `memory` tool updates
- replacement/consolidation pressure when full

This is a strong fit, not a speculative reinterpretation.

### 2. Warm memory uses the right official substrates

The plan uses:

- skills for procedural frames
- context files for stable repo/operator guidance

That is aligned with official Hermes semantics and progressive disclosure.

The design correctly avoids turning skills into factual dumping grounds and instead uses them as reusable procedures and mode carriers.

### 3. Cold memory remains explicit and selective

The current implementation keeps cold material in file artifacts such as:

- `latest-summary.json`
- `windows.json`
- `analysis-candidates.json`
- `retrieval-index.json`
- `overlay-report.json`
- `runs.jsonl`

This is a good fit with official Hermes because it keeps large evidence stores outside always-injected memory and relies on selective retrieval instead of hidden prompt growth.

### 4. Dreaming is correctly framed as maintenance, not magic

The dreaming toolkit is deterministic-first:

- export sessions
- count signals
- extract windows
- rank review candidates
- build retrieval bundles
- render operator summaries

This is exactly the kind of local layering that should happen before asking for upstream features.

### 5. The retrieval index stays local and low-conflict

`build_retrieval_index()` is a repo-local selector over:

- dream artifacts
- context files
- log files
- analysis windows

It does not patch Hermes core or claim to be an official retriever. That boundary discipline is good.

## What should remain local for now

These parts are useful, but still too heuristic or repo-specific to treat as upstream-ready abstractions.

### Mode routing heuristics

The current four-mode model:

- coding
- operator
- reflection
- conversational

is useful locally, but the keyword rules and scoring remain hand-tuned and repo-shaped.

### Retrieval scoring and token estimates

The source tagging, scoring weights, and estimated-token logic are practical prototype heuristics, not yet stable general interfaces.

### Overlay maintenance surfaces

Patch export, working-tree diff export, and overlay drift reporting are valuable here, but they are clearly local to this repo’s modified-Hermes workflow.

### MOTD/operator glue

The SSH/MOTD renderer is good operator UX, but it is host-local glue, not a core Hermes memory abstraction.

## Plausible upstream candidates later

These are the areas most likely to justify upstream discussion once local usage proves they are durable.

### 1. Mode-aware retrieval bundles

A first-class way to say:

- current task mode
- preferred retrieval classes
- preferred evidence bundle size

could be upstream-worthy if multiple repos end up reinventing it.

### 2. Memory/skill utility accounting

The repo is moving toward evidence-based judgments about:

- overused skills
- stale memories
- demotion candidates
- context rent

That kind of utility accounting could become a useful official abstraction if it stays deterministic and explainable.

### 3. Maintenance reports from session history

The combination of:

- tool-usage windows
- memory churn
- repeated recall
- ranked analysis candidates

looks like a plausible future official report surface, especially if it can sit on top of hooks/session export without invasive core changes.

### 4. Promotion/demotion guidance between layers

Official Hermes may eventually benefit from stronger guidance or tooling around:

- what belongs in built-in memory
- what belongs in skills/context files
- what should stay cold

But that should only be proposed after the local audit/compression tooling proves useful in practice.

## Risks and gaps

### 1. Final review is still blocked by missing hot-memory audit tooling

The biggest remaining gap is `hermes-tailchat-add`.

Without deterministic audit/compression tooling for `USER.md` and `MEMORY.md`, the architecture has a good theory of hot memory but not its main validation loop.

### 2. Retrieval remains heuristic

The retrieval index is intentionally deterministic, but still heuristic:

- keyword mode classification
- static source tags
- static weighting
- rough token estimates

That is acceptable for a prototype but still a maintainability risk if it grows without stronger manifests or decision records.

### 3. Hidden memory/provider utility is still invisible

The current evidence model sees explicit tool usage well, but not:

- hidden built-in memory utility
- provider-prefetch usefulness
- context that helped without surfacing through a tool call

This is a known limitation and should remain explicit in docs/reviews.

### 4. Cold artifact retention is still underspecified

The repo now generates useful cold artifacts, but there is not yet a clear retention/rotation policy for long-term buildup.

### 5. Reviewability of later actions is not fully closed-loop yet

The repo now has good evidence collection, but still needs stronger decision-record style outputs for:

- keep / compress / move / remove memory actions
- keep / patch / split / retire skill actions

That is the next maintainability step after raw evidence collection.

## Upstream-boundary judgment

Current boundary discipline is good.

What the repo does now:

- uses official Hermes primitives as substrate
- layers deterministic file-based tooling on top
- keeps repo/operator-specific heuristics local
- avoids pretending local orchestration is an upstream feature already

That is the right posture.

The repo should continue proving value locally before proposing upstream work.

## Recommended next steps

### Must do before final closure of `hermes-tailchat-rev`

1. Implement `hermes-tailchat-add`
   - deterministic hot-memory audit/compression recommendations
   - explicit keep-hot / compress / move / remove outputs

2. Add retention policy for cold dreaming artifacts
   - especially `runs.jsonl`, windows, and derived bundles over time

3. Add reviewable decision-record outputs
   - so maintenance recommendations become auditable actions rather than just ranked artifacts

### Good follow-on discipline

- keep upstream discussion focused on abstractions that survive repeated local use
- do not upstream repo-local heuristics, host glue, or overlay-specific operator surfaces
- continue to prefer hooks/files/cron/skills layering before core patching

## Bottom line

The architecture is on the right track.

It is strongly aligned with official Hermes primitives, keeps most complexity in local deterministic tooling, and draws a sensible line between:

- hot memory
- warm procedural/frame memory
- cold evidence stores

The retrieval prototype is good enough to justify continued work.

But the program is not review-complete until the hot-memory audit/compression slice exists. For now, this should be treated as a positive interim review with one major remaining dependency: `hermes-tailchat-add`.
