# Session-Aware Tailchat Abstraction Layer Plan

> For Hermes: use this as the architectural plan before implementation. Do not collapse Tailchat into a thin raw projection of Hermes state without first validating the staged bridge described here.

Goal: let a user move between Tailchat and Hermes CLI with shared session identity and eventually curated transcript continuity, while keeping Tailchat resilient to Hermes internal changes.

Architecture: Tailchat remains the UX-owned abstraction layer and local product boundary. Each Tailchat conversation gets an explicit linked Hermes session identity plus controlled synchronization rules for titles and selected transcript content. Hermes remains the execution engine and durable session runtime, but Tailchat keeps its own presentation model and import/export adapter.

Tech stack: FastAPI backend, Tailchat SQLite store, Hermes SessionDB in `~/.hermes/state.db`, local `LocalHermesProvider`, SSE event delivery.

---

## Decision summary

Recommended direction:
1. Keep Tailchat as a separate abstraction layer.
2. Add explicit `hermes_session_id` linkage to every Tailchat conversation.
3. Treat Hermes as the canonical execution session identity.
4. Do not yet treat Hermes raw transcript/schema as Tailchat's direct source of truth.
5. Introduce a curated sync boundary for names and user-visible messages.

Rejected-for-now direction:
- Tailchat directly reading and rendering Hermes `state.db` as if it were its own app model.

Why:
- faster to evolve mobile UX safely
- lower risk from Hermes schema/event changes
- easier to hide raw tool/internal messages
- still enables incremental CLI/mobile continuity

---

## What is true today

Verified current behavior:
- Tailchat `conversation_id` is already passed to Hermes as `session_id`.
- Hermes `api_server` sessions in `~/.hermes/state.db` therefore already share IDs with Tailchat conversations.
- Tailchat titles in `tailchat.db` are not synchronized to Hermes session titles.
- Tailchat transcript in `tailchat.db` is not synchronized with later CLI activity against the same Hermes session.
- Tailchat renders from its own `messages` table, not from Hermes session history.

Consequence:
- low-level identity linkage already exists
- named-session continuity and transcript continuity do not yet exist

---

## Product goals for this feature

Must-have goals:
- a Tailchat conversation can be explicitly linked to one Hermes session
- the link is stable across restarts
- users can intentionally resume the same session from CLI or mobile
- session names are understandable and predictable
- Tailchat stays robust when Hermes internals change

Nice-to-have goals:
- Tailchat chat list can show the linked Hermes title
- users can attach Tailchat to an existing named Hermes session
- Tailchat can import later CLI-generated user/assistant turns for the same session

Non-goals for the first slice:
- perfect bidirectional parity for all Hermes message roles
- raw display of every tool event or reasoning artifact from Hermes state
- direct dependence on every detail of Hermes `state.db`
- multi-user collaborative editing semantics

---

## Main risks and how this can backfire

### 1. Title collisions

Examples:
- user names a Tailchat chat `Research`
- a CLI Hermes session already has title `Research`
- Hermes title uniqueness rules reject the update

Risk:
- confusing failures or accidental attachment to the wrong session

Policy:
- session identity is never resolved by title alone when an explicit `hermes_session_id` exists
- titles are metadata, not identity
- on collision, preserve the link by ID and surface a non-destructive warning
- if needed, offer suggested variants like `Research #2`

### 2. Transcript duplication

Examples:
- Tailchat stores a user/assistant turn locally
- later imports the same turn from Hermes and duplicates it

Risk:
- ugly transcripts and loss of trust

Policy:
- introduce per-message provenance metadata, e.g. `origin = tailchat_local | hermes_import`
- store a stable external reference when importing Hermes messages
- make imports idempotent by Hermes message identity or deterministic fingerprint

### 3. Abstraction leakage

Examples:
- Hermes tool messages appear as noisy chat bubbles
- internal reasoning/tool-call sequencing becomes visible in mobile UI

Risk:
- degraded UX and strong coupling to Hermes internals

Policy:
- import only a curated visible subset for Tailchat by default:
  - user
  - assistant final text
  - selected system notes
- keep tool/reasoning details available only through debug or event-history surfaces if desired

### 4. Version drift / Hermes updates

Examples:
- Hermes changes schema, event types, title behavior, or storage details

Risk:
- Tailchat breaks after Hermes upgrade

Policy:
- centralize Hermes integration behind one adapter module
- prefer Hermes API/provider methods over direct SQL reads where practical
- if direct SessionDB reads are needed, keep them isolated in a tiny compatibility layer
- never scatter Hermes schema assumptions across UI and API code

### 5. Concurrent continuation from CLI and mobile

Examples:
- user sends a mobile message while a CLI continuation is active
- external messages arrive while Tailchat is open

Risk:
- confusing ordering or stale UI

Policy:
- Tailchat must tolerate foreign writes to linked sessions
- imports should be append-safe and ordered by Hermes event/message timestamps
- live UI should mark externally imported turns if needed
- first implementation can be eventual consistency on refresh/open, not perfect real-time bidirectional sync

### 6. Incorrect session attachment

Examples:
- a user wants a fresh mobile thread with similar title, but the app auto-resumes an older session

Risk:
- unintended context carryover

Policy:
- default action for a new Tailchat chat remains: create a fresh linked Hermes session
- attaching to an existing Hermes session is explicit user intent, not automatic fuzzy matching

---

## Recommended architecture

## Canonical identities

Tailchat conversation remains the app-owned object.
Hermes session remains the execution/runtime object.

Required invariant:
- each Tailchat conversation has zero or one linked Hermes session
- after migration, new conversations should always have exactly one linked Hermes session

Data model recommendation:
- Tailchat conversation:
  - `id` (Tailchat-owned conversation ID)
  - `title`
  - `hermes_session_id` (nullable during migration only)
  - `sync_state` (`local_only`, `linked`, `sync_error`)
  - `last_hermes_import_at` (timestamp/cursor)
  - `link_mode` (`owned`, `attached`)
- Tailchat message:
  - existing local fields
  - `origin` (`tailchat`, `hermes_import`)
  - `external_message_ref` (nullable unique reference for imported Hermes messages)

Notes:
- in today's implementation, Tailchat already uses `conversation_id == Hermes session_id`
- keep supporting that as the simplest `owned` mode
- still add the explicit column so the contract is visible and evolvable

## Ownership model

Two link modes:

1. `owned`
- Tailchat created the conversation/session pair
- default for ordinary new chats
- safest and simplest initial path

2. `attached`
- Tailchat intentionally attaches to an existing Hermes session created elsewhere, e.g. CLI
- requires explicit user action
- enables cross-surface pickup of pre-existing CLI work

This avoids implicit title-based magic.

## Sync model

### Titles

Direction for first implementation:
- Tailchat-created chats:
  - Tailchat remains initial title source
  - optionally mirror into Hermes session title
- attached Hermes sessions:
  - Hermes title becomes the initial display title in Tailchat

Conflict rule:
- ID link wins over title sync
- title sync failures do not sever the link
- show warning state or keep local display title if Hermes rejects a rename

### Transcript

Direction for first implementation:
- Tailchat writes local transcript immediately for good UX
- Hermes continues to store full underlying session transcript
- Tailchat may import user-visible turns from Hermes on demand:
  - when opening a conversation
  - on explicit refresh
  - optionally after a local run completes

Import scope for first implementation:
- import only user and assistant messages
- skip raw tool messages
- optionally convert selected system messages into Tailchat-friendly notes

### Real-time behavior

Not required in the first slice:
- full live two-way session mirroring between CLI and Tailchat

Good enough initially:
- eventual sync on open/refresh/reconnect

---

## Collision and failure policy

### Title collision policy

When syncing Tailchat title to Hermes:
- try exact requested title
- if Hermes rejects because title exists:
  - keep local Tailchat title unchanged
  - record sync warning
  - optionally suggest `Title #2` in UI/action later

Do not:
- silently reattach to a different Hermes session with that title
- silently rename to another title without telling the user

### Session attach policy

When attaching by name/title:
- resolve only through explicit Hermes lookup UI/command
- present exact session metadata before attach:
  - session ID
  - title
  - started_at / last_active
  - source (`cli`, `api_server`, etc.)
- user confirms attachment

Do not:
- auto-attach by fuzzy title match during ordinary new chat creation

### Import idempotency policy

When importing from Hermes:
- store external identity per imported message
- enforce unique `(conversation_id, external_message_ref)`
- if already imported, update or skip instead of duplicating

### Hermes unavailable policy

If Hermes state/session access fails:
- Tailchat remains usable for local conversations already stored
- linked conversation shows degraded sync state
- user can still view local transcript
- retries happen later; no destructive repair attempts

---

## Pros and cons of the recommended hybrid

### Pros
- preserves Tailchat as a UX-focused abstraction layer
- avoids strong coupling to Hermes internal schema everywhere
- lets mobile UI stay clean and opinionated
- keeps room for curated imports rather than raw message leakage
- enables staged rollout with measurable checkpoints
- easier rollback if interoperability proves messy

### Cons
- some data duplication remains
- sync logic must be built carefully
- true continuity arrives in stages rather than instantly
- more code than a naive direct-source-of-truth approach

### Why this is still the right choice
For a fast-moving single-user prototype, resilience to Hermes changes and freedom to shape UX matter more than achieving perfect storage purity immediately.

---

## Staged rollout plan

### Stage 0: document the contract
Objective: make the intended boundary explicit before changing behavior.

Deliverables:
- document Tailchat ↔ Hermes session contract
- define owned vs attached link modes
- define title conflict and import idempotency rules

### Stage 1: explicit linkage metadata
Objective: make session linkage durable and inspectable.

Deliverables:
- add `hermes_session_id`, `sync_state`, `link_mode`, `last_hermes_import_at` to Tailchat conversations
- backfill existing rows where `hermes_session_id = conversation_id`
- expose linked session metadata in API responses
- optionally show a `resume in CLI` hint using the linked session ID

Expected result:
- no behavior surprise yet
- data model becomes honest about the integration

### Stage 2: title interoperability
Objective: align names without making names the identity layer.

Deliverables:
- Tailchat-owned conversations can push title updates to Hermes title
- attached conversations initialize display title from Hermes title
- sync errors are visible but non-destructive

Expected result:
- chat list can meaningfully correspond to named Hermes sessions

### Stage 3: attach existing Hermes sessions
Objective: support intentional pickup of a CLI session on mobile.

Deliverables:
- API endpoint to list attachable Hermes sessions
- endpoint/action to attach one to a new Tailchat conversation
- clear UI affordance for attach vs new chat

Expected result:
- explicit cross-surface continuity begins

### Stage 4: curated transcript import
Objective: make later CLI activity visible in Tailchat.

Deliverables:
- adapter that reads Hermes session messages through one boundary module
- import only user-visible turns
- idempotent mapping into Tailchat messages
- import on open/refresh/reconnect

Expected result:
- user can resume in CLI, come back to mobile, and see meaningful new turns

### Stage 5: optional near-real-time external update sync
Objective: tighten the continuity loop if it proves valuable.

Deliverables:
- poll or event-driven detection of external session changes
- live insertion/update of imported visible messages
- better external-origin indicators if needed

Expected result:
- stronger seamlessness, but only after earlier stages are stable

---

## Acceptance criteria for the first safe implementation

A first implementation should be considered successful if all are true:
- every new Tailchat conversation has explicit linked Hermes session metadata
- existing conversations are safely backfilled
- Tailchat can show the linked Hermes session ID
- Tailchat can derive a CLI resume hint from that ID
- renaming a Tailchat chat no longer risks confusing session identity
- no direct UI code reads Hermes DB schema directly
- no transcript duplication is introduced

---

## What not to do yet

Avoid these shortcuts:
- do not make Tailchat render directly from Hermes raw `messages` table in the UI
- do not infer identity from title equality
- do not auto-attach to the latest matching title without user intent
- do not import tool messages into the normal chat list by default
- do not spread Hermes schema reads across multiple files

---

## Recommended first PR after planning

Smallest safe first PR:
1. schema migration in Tailchat store for explicit Hermes linkage metadata
2. API response updates exposing linkage
3. backfill existing conversations with `hermes_session_id = conversation_id`
4. UI hint showing linked Hermes session ID / CLI resume command
5. tests for migration and API serialization

Why this PR first:
- valuable immediately
- low risk
- no deep transcript coupling yet
- creates the foundation for titles and attach/import work later

---

## Open questions to answer before Stage 3+

- Should Tailchat support multiple Tailchat conversations attached to the same Hermes session, or forbid that?
  - recommendation: forbid by default at the app layer
- Should Tailchat allow local display title differing from Hermes title?
  - recommendation: yes, but keep one visible as canonical and treat the other as optional presentation metadata
- Should imported external turns be visibly marked as coming from CLI?
  - recommendation: probably yes at first, subtle badge only
- Is eventual consistency on conversation open enough, or do we need live cross-surface updates?
  - recommendation: start with open/refresh sync only

---

## Bottom line

Build a session-aware abstraction layer, not a raw state-db mirror.

That gives the project:
- shared session identity
- future shared naming
- future curated transcript continuity
- less fragility under Hermes updates
- room to keep Tailchat opinionated and mobile-friendly
