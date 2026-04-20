# Official Hermes primitives for a memory hierarchy

Date: 2026-04-19
Bead: `hermes-tailchat-tn2`
Status: completed research

## Goal

Review official Hermes documentation to determine which existing Hermes features already support a hot/warm/cold memory architecture, which features can approximate frame-of-mind retrieval, and which gaps still require local layering or eventual upstream work.

## Sources reviewed

Official Hermes docs/pages reviewed:

- Persistent Memory
- Memory Providers
- Skills System
- Context Files
- Context References
- Event Hooks
- Scheduled Tasks (Cron)
- CLI help locally for `hermes insights`, `hermes sessions`, and `hermes memory`

## Executive summary

Official Hermes already provides most of the primitives needed for a memory hierarchy, but not a single integrated subsystem that manages the hierarchy explicitly.

The closest mapping is:

- **Hot memory** → built-in `USER.md` + `MEMORY.md`
- **Warm memory** → skills with progressive disclosure
- **Cold memory** → external memory providers, context files, and arbitrary files/logs referenced on demand
- **Selective retrieval** → provider prefetch + skills + context references
- **Background maintenance** → cron
- **Provenance/telemetry hooks** → event hooks / plugin hooks

So the problem is less "Hermes lacks the parts" and more "Hermes lacks the orchestration layer that turns the parts into an explicit memory hierarchy with mode-guided retrieval."

## What official Hermes already solves

### 1. Built-in bounded memory solves hot, always-injected memory

Official Persistent Memory docs describe:

- `MEMORY.md` for the agent's durable notes
- `USER.md` for the user's durable profile/preferences
- hard character limits:
  - `MEMORY.md` 2,200 chars
  - `USER.md` 1,375 chars
- both are injected as a **frozen snapshot at session start**
- the `memory` tool can add, replace, or remove entries
- when full, the documented behavior is to consolidate or replace entries

Implication:

- Official Hermes already treats built-in memory like **small curated RAM**.
- This supports the direction of optimizing `USER.md`/`MEMORY.md` for signal rather than trying to make them large archives.

### 2. Memory providers solve large supplemental storage better than built-in memory can

Official Memory Providers docs describe external providers that can:

- inject provider context
- prefetch relevant memories before each turn
- sync conversation turns after responses
- extract memories on session end (provider-dependent)
- mirror built-in memory writes
- add provider-specific search/store/manage tools

Official docs also state:

- only one external provider can be active at a time
- built-in memory remains active alongside it

Implication:

- External memory providers are the closest official Hermes feature to **large disk-like memory** that supplements hot built-in memory.
- They are additive rather than a replacement for built-in memory.
- They are a good fit for large searchable storage, not for expanding always-injected memory.

### 3. Skills solve procedural warm memory

Official Skills docs describe skills as:

- on-demand knowledge documents
- loaded only when needed
- using a **progressive disclosure** pattern
- stored under `~/.hermes/skills/`
- extensible through external skill directories
- available through slash commands and natural interaction

Documented loading pattern:

- `skills_list()` → list/description/category
- `skill_view(name)` → full skill content
- `skill_view(name, path)` → specific referenced file

Implication:

- Skills already implement a **warm, selectively loaded procedural memory** layer.
- They are the strongest official candidate for carrying reusable "frames" or procedural modes of thought.

### 4. Context files solve larger stable non-hot context

Official Context Files docs describe automatically discovered files such as:

- `.hermes.md` / `HERMES.md`
- `AGENTS.md`
- `CLAUDE.md`
- `SOUL.md`
- `.cursorrules`

Important documented behavior:

- `SOUL.md` is global to the Hermes instance
- project context file priority is explicit
- `AGENTS.md` and related files are discovered progressively from the working tree

Implication:

- Context files are the official place for **stable project/operator guidance that should not live in tiny built-in memory**.
- Some currently tempting `USER.md` / `MEMORY.md` content is likely better placed in context files.

### 5. Context references solve selective large retrieval

Official Context References docs describe on-demand inclusion of:

- `@file:`
- `@folder:`
- `@diff`
- `@staged`
- `@git:N`
- `@url:`

Implication:

- This is the strongest official answer to **pull large storage only when needed**.
- Context references are a built-in mechanism for fetching the smallest necessary evidence instead of injecting large stores by default.

### 6. Cron solves background maintenance loops

Official cron docs describe:

- one-shot and recurring tasks
- attaching zero/one/multiple skills
- delivery back to origin or other targets
- fresh sessions per cron run
- pause/resume/edit/remove

Implication:

- Cron is already the right official primitive for dreaming, maintenance, audits, summaries, and periodic retrieval work.

### 7. Hooks solve logging/provenance surfaces

Official Hooks docs describe two hook systems:

- gateway hooks via `~/.hermes/hooks/HOOK.yaml` + `handler.py`
- plugin hooks via `ctx.register_hook()`

Documented uses include:

- logging
- alerts
- webhooks
- tool interception
- metrics
- guardrails

Implication:

- Hooks are the best official low-conflict place to add provenance/usage logging without immediately patching Hermes core.

## What official Hermes can approximate but does not fully formalize

### 1. A hot/warm/cold hierarchy can be composed, but is not described as such

Hermes documentation does not officially name a memory hierarchy, but the pieces line up naturally:

- hot: built-in memory
- warm: skills
- cold: memory providers + files/logs/context references

Implication:

- The hierarchy can be built today as a local architecture layered on top of official features.
- Hermes does not yet present it as one unified subsystem.

### 2. Frame-of-mind retrieval can be approximated through skills, context selection, and cron prompts

There is no official documented concept named "frame of mind" or a native mode-guided retriever.

But it can be approximated by combining:

- skills as procedural frames
- context files as stable mode-specific guidance
- context references as selective evidence loading
- cron prompts / explicit task prompts that name the mode

Implication:

- Official Hermes already has enough primitives to approximate mode-guided retrieval locally.
- The missing piece is orchestration logic that chooses what to retrieve based on the current mode.

## What appears to be missing from official Hermes today

### 1. No first-class integrated memory hierarchy manager

There is no documented official feature that explicitly manages:

- hot vs warm vs cold memory
- promotion/demotion between layers
- retention policy / eviction policy across layers

### 2. No first-class frame-of-mind retrieval subsystem

There is no official documented mechanism that says:

- current mode is coding/operator/reflection/conversational
- retrieval policy changes based on that mode
- memory and skills are selected differently because of that mode

### 3. No official dreaming/reflection subsystem

There is no official documented built-in feature that:

- periodically audits memory/skills
- scores their utility
- proposes compress/move/remove actions
- turns logs and session history into maintenance suggestions

### 4. No official skill-vs-memory utility/rent scoring

Official docs do not describe a built-in mechanism for:

- context cost accounting per memory/skill
- utility scoring
- contradiction/staleness scoring
- demotion from hot memory into colder stores

### 5. No official overlay-maintenance support for local Hermes modifications

Nothing official appears to manage:

- local patch exports/imports
- upstream drift reports
- rebase-ready local overlays

This remains a local concern.

## Practical architectural implications for this repo

### What should remain hot

Keep in built-in memory only facts that truly earn always-on injection:

- durable user preferences
- stable environment facts
- repeated corrective guidance
- facts that materially reduce future steering

### What should move warm

Use skills for:

- reusable procedures
- review lenses
- task-oriented or mode-like guidance
- frame bundles for recurring situations

### What should move cold

Use cold searchable storage for:

- dream artifacts and windows
- session summaries
- provenance logs
- patch/overlay reports
- detailed rationale and history
- evidence bundles for later AI analysis

### Best local strategy

Stay close to official Hermes by building the orchestration locally on top of:

- built-in memory
- memory providers
- skills
- context files
- context references
- cron
- hooks

This minimizes upstream conflict while still enabling a genuine memory hierarchy.

## Recommended next step for the design bead

The design bead should define an explicit local architecture:

- **Hot memory**
  - `USER.md`
  - `MEMORY.md`
- **Warm memory**
  - skills
  - possibly grouped by retrieval mode
- **Cold memory**
  - dream artifacts
  - logs
  - external provider state
  - searchable repo-local notes
- **Frame-of-mind retrieval policy**
  - coding
  - operator
  - reflection/dream
  - conversational
- **Retrieval policy output**
  - what to keep hot
  - what to load as skill
  - what to fetch selectively via cold-store index/context references

## Bottom line

Official Hermes already provides most of the building blocks for a memory hierarchy, but not the hierarchy controller itself.

That means the maintainable path is:

1. use official Hermes primitives as the substrate
2. implement local deterministic orchestration on top
3. upstream only the abstractions that later prove generally useful
