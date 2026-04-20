# Safe aggressive dependency updates for Hermes Tailchat

Date: 2026-04-20
Primary backlog anchor: `hermes-tailchat-0lb`

## Why this plan exists

The repo already has an explicit preference for staying aggressively current on dependencies, including major versions. That posture is reasonable for a single-user tailnet-only service that should not rot on old packages. But "update aggressively" is only a net win if breakage and compromise are contained.

For this repo, the user preference is clear:
- brief interruptions are acceptable
- silent or sticky failures are not
- rollback should be automatic where practical
- prevention should come before recovery when the tradeoff is reasonable
- security work should reduce real blast radius, not just add fashionable complexity

So the architecture direction should not be "containers first" or "more moving parts first". It should be:
1. explicit contracts around dependency seams
2. reproducible and rollbackable release artifacts
3. smoke-gated promotion of a candidate build
4. stronger runtime sandboxing on the single host
5. good documentation of assumptions, failure modes, and operator expectations
6. only then, higher-complexity isolation such as rootless containers or service splits if the value is proven

## Current observed state

Observed in repo as of this planning pass:
- app is a single FastAPI service with a local Hermes provider abstraction used in practice
- tests are strong on in-process backend behavior but still weak on real-provider and browser behavior
- deployment is currently restart-in-place via `scripts/deploy-local.sh`
- current deploy verification is only a `/health` poll after restart
- there is not yet a candidate-port or automatic rollback workflow
- dependencies are currently minimal and defined in `pyproject.toml`
- architecture docs still contain earlier stack assumptions that are broader than the current shipped shape

## Architecture recommendation in one paragraph

Keep Hermes Tailchat systemd-first, single-host, SQLite-backed, and tailnet-only for now. Add an explicit provider contract, an event/rendering contract, and a release/deploy contract. Promote updates through a localhost candidate instance and smoke gate before switching traffic. Preserve a previous known-good release so rollback is fast and automatic. Harden the runtime with systemd sandboxing before introducing containers. Treat rootless containers as a possible later packaging refinement, not as the primary safety strategy.

## What we should and should not optimize for

### Optimize for
- one-user reliability
- fast recovery after a bad update
- confidence before rollout
- low operator babysitting burden
- low blast radius if a dependency is vulnerable or malicious
- small, reviewable, frequently validated changes

### Do not optimize for yet
- multi-user scale
- zero-downtime deploys at all costs
- active-active service meshes
- container orchestration
- generic enterprise platform patterns disconnected from this repo's actual threat model

## Assumptions to check instead of blindly inheriting

This work should include explicit assumption audits rather than treating old docs or intuition as truth.

### Runtime assumptions
- Is FastAPI + the current local provider still the intended core architecture, or has the repo drifted toward a different split?
- Which directories actually need write access at runtime?
- Which network destinations must be reachable for ordinary operation?
- Is SQLite still the right state store for the next horizon, given one user and candidate deploy needs?

### Deploy assumptions
- Can a second local instance safely run against a copied database for candidate smoke?
- What exactly must a candidate prove before traffic can switch?
- Which health checks are necessary beyond `/health`?
- What must happen automatically if the new release boots but fails app-level smoke?

### Dependency assumptions
- Which dependencies form distinct contract surfaces: provider, web framework, persistence, frontend behavior, deploy scripts?
- Which package managers and lock/hash surfaces actually exist in this repo?
- Which updates may be auto-merged eventually, and which must always stay human-reviewed?

### Threat-model assumptions
- Which realistic attacker wins matter most here: malicious update, vulnerable transitive package, compromised action, or broken major-version bump?
- Which mitigations actually reduce impact on a single-user tailnet-only host?
- Which secrets or authorities are currently too close to the web process?

## Proposed phased architecture

## Phase 0 — document reality and assumptions before hardening

Goal: make the current architecture, authority, and rollout assumptions explicit before adding automation.

Deliverables:
- a current-state architecture note aligned with the shipped app rather than older aspirational stack docs
- an assumptions-and-invariants document for updates and deploys
- a dependency surface inventory tied to package managers, runtime authorities, and test seams
- a first-class authority and trust-boundary inventory covering writable paths, network egress, secrets/env exposure, subprocess/tool authority, and external codebases trusted at runtime
- a short decision note explaining why the near-term path is systemd-first rather than container-first

Why first:
- bad safety work often starts from stale architecture beliefs
- contract and rollout work should be tied to the current product, not to outdated design sketches

## Phase 1 — formalize testable seams around risky dependencies

Goal: shift confidence left by defining interfaces that dependency updates must continue to satisfy.

Primary seams:
1. Hermes provider contract
   - explicit protocol or abstract interface
   - shared contract tests for dummy and real local provider implementations
2. event contract
   - normalized event sequences and replay behavior
   - rate-limit snapshot parsing/fallback expectations
3. frontend behavior contract
   - folded tool-event behavior
   - approval modal behavior
   - reconnect/replay behavior
   - `/hermes` subpath behavior
4. deploy/health contract
   - what a candidate release must prove before promotion
   - what a post-switch smoke must prove before the old release can be discarded
   - which candidate-mode side effects must be disabled or isolated during validation

Why this phase matters:
- dependency upgrades are safer when they break a named contract in CI rather than a user's live session after rollout

## Phase 2 — add candidate promotion and automatic rollback

Goal: make failed updates self-healing.

Recommended pattern:
- build immutable release directories
- keep per-release virtual environments
- start candidate on a second localhost port
- run smoke checks against the candidate
- switch traffic only after smoke passes
- retain previous release for quick rollback
- if post-switch validation fails, automatically switch back and restart the previous release

Important constraints:
- one active writer at a time against the real database
- candidate smoke should use either a copied DB or read-only / isolated state when feasible
- candidate mode must not run the same recovery/job-poller/approval side effects as the live writer unless explicitly isolated
- promotion rules must account for SQLite schema compatibility: either no irreversible schema change before promotion, expand/contract migration discipline, or a pre-switch backup/restore path that is actually tested
- this is blue/green-lite, not full active-active

Why this phase matters:
- restart-in-place plus `/health` is too weak for major-version churn
- fast rollback reduces the operational cost of staying current

## Phase 3 — sandbox the runtime harder on the host

Goal: reduce blast radius if a dependency misbehaves or is compromised.

Primary moves:
- tighten systemd service hardening options
- reduce writable paths to the minimum runtime state directories
- restrict network and privilege where practical
- separate secrets/config from code and release artifacts more clearly

Suggested starting point:
- `NoNewPrivileges=yes`
- `PrivateTmp=yes`
- `ProtectSystem=strict`
- `ProtectHome=` as tight as feasible
- explicit `ReadWritePaths=`
- `ProtectKernelTunables=yes`
- `ProtectKernelModules=yes`
- `ProtectControlGroups=yes`
- `MemoryDenyWriteExecute=yes`
- `RestrictAddressFamilies=` only as needed
- `LockPersonality=yes`
- `RestrictRealtime=yes`
- `UMask=0077`

Why before containers:
- these changes provide real containment on the actual host you run today
- a casually permissive container would be less useful than a tightly sandboxed systemd unit

## Phase 4 — selectively separate authority if needed

Goal: isolate the dangerous parts only if the complexity pays for itself.

Candidate future split:
- web/UI process: low privilege, serves API/UI, owns little authority
- provider/worker adapter: more dangerous, handles tool/provider interactions
- optional broker/guard path: mediates approvals, secrets, or high-risk side effects

Do this only if one of these becomes true:
- the provider side needs materially different privileges than the web tier
- updates repeatedly break because too much authority is concentrated in one process
- sandboxing a single service cannot reduce risk enough

## Phase 5 — containers only if they solve a now-proven problem

Containers are optional future packaging, not the strategy itself.

Good reasons to add them later:
- rootless immutable packaging
- easier artifact reproducibility across hosts
- easier candidate boot/cleanup
- better host contamination boundaries

Bad reasons:
- "containers equal security"
- "containers solve dependency trust"
- "containers automatically solve rollback"

If adopted later, prefer:
- rootless Podman
- systemd/quadlet integration
- read-only root filesystem
- tiny writable volumes
- explicit capability drops

## Documentation work that should be first-class, not an afterthought

The repo should document not only the happy path but also the assumptions behind it.

Required doc slices:
- current architecture reality vs older architectural proposals
- explicit dependency seam contracts and where each is tested
- candidate promotion and rollback runbook
- runtime trust boundaries, writable-path inventory, and secret/env exposure by process
- dependency update policy by surface: app deps, tooling deps, GitHub Actions, scanners, and the local Hermes runtime tree
- assumptions log: what is believed, how it was checked, and what remains provisional

This matters because future-you should not need chat archaeology to understand why the repo chose systemd-first rollbackable deploys instead of jumping straight to containers.

## Validation strategy

### Before rollout
- backend/unit/contract tests
- smoke against candidate localhost port
- opt-in real-provider smoke where environment permits
- browser smoke for the most fragile UI behaviors once available

### After promotion
- minimal post-switch smoke
- service health and log sanity check
- automatic rollback trigger if the promoted release fails the agreed contract

### For every architectural claim
Every new boundary should answer:
- what interface is being protected?
- what test proves it?
- what assumption does it rely on?
- what rollback exists if it still fails in practice?

## Recommended new backlog shape

The current dependency-update parent bead is too broad to safely execute as a single slice. It should be supported by child beads for:
1. current-state and assumption audit
2. authority / trust-boundary inventory
3. contract formalization
4. release candidate / rollback workflow
5. runtime sandboxing
6. documentation and runbooks that match reality
7. follow-up review of whether containers or authority splits are now justified

Those beads should also force documentation and assumption-checking to ship in the same sequence, not as deferred cleanup.

The umbrella bead for aggressive updates should stay explicitly blocked on baseline CI and core chat `/hermes` smoke coverage, so "aggressive updates" never degrades into "automated version churn without enough evidence".

## Success criteria for the overall direction

We are on the right path when all of the following become true:
- dependency updates routinely land through a repeatable gate instead of ad hoc confidence
- a broken update self-recovers or is reverted quickly without manual debugging marathons
- architecture docs describe the shipped system accurately
- trust boundaries and writable paths are explicit
- the next time we ask "should this be containerized?" the answer is based on measured pain, not cargo culting
