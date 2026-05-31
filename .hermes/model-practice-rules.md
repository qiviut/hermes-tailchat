# hermes-tailchat — model upkeep rules

If we keep models for this repo, they are part of the work, not optional decoration.

## Rule 1 — runtime-flow change => update the sequence/trust model in the same slice

**When doing X**
- changing run lifecycle
- changing approval handling
- changing retry behavior
- changing background job behavior
- changing SSE/event publication semantics
- changing restart/recovery behavior

**Also do Y on the model**
- update `.hermes/run-approval-trust-sequence.md` in the same slice
- add 1-3 bullets in commit/PR notes naming what changed in the flow:
  - new step
  - removed step
  - changed retry/stop condition
  - changed approval gate

**To get Z effect**
- prevent flow bugs from hiding in multi-file diffs
- make review faster for async/stateful changes
- keep the runtime model trustworthy enough to use during debugging

**Done means**
If the runtime behavior changed and the sequence/trust doc still describes the old behavior, the slice is not done.

---

## Rule 2 — authority/trust-boundary change => update the C4-lite or trust notes in the same slice

**When doing X**
- changing Hermes vs Codex responsibility split
- adding/removing a subprocess or worker path
- changing what the browser can request or resolve
- changing what secrets/env/tool authority a path has
- changing untrusted-ingestion or sanitizer boundaries

**Also do Y on the model**
- update `.hermes/c4-lite.md` if a container/component boundary changed
- update `.hermes/run-approval-trust-sequence.md` if an authority boundary changed in flow
- add one sentence in commit/PR notes answering:
  - what gained authority?
  - what lost authority?
  - what boundary moved?

**To get Z effect**
- catch authority creep early
- keep the trust story explicit instead of implied
- make security-sensitive review cheaper

**Done means**
If a boundary moved and neither model was touched, the slice is incomplete.

---

## Rule 3 — non-trivial review => use the model as a gate, not a souvenir

**When doing X**
- reviewing before commit/PR any non-trivial slice touching:
  - `app/main.py`
  - `app/hermes_provider.py`
  - `app/codex_runner.py`
  - `app/untrusted_ingest.py`
  - approval/retry/recovery/background-job behavior

**Also do Y on/with the model**
- check the slice against:
  1. `.hermes/c4-lite.md`
  2. `.hermes/run-approval-trust-sequence.md`
- record one of these outcomes in review notes:
  - `model unchanged, code still matches`
  - `model updated with slice`
  - `model obsolete -> remove/replace it`

**To get Z effect**
- force a decision about model trustworthiness
- stop stale models from accumulating quietly
- make “we use models” mean something in practice

**Done means**
A non-trivial slice cannot close with silent model drift.

---

## Rule 4 — if the model keeps going stale, delete it

**When doing X**
- noticing repeated drift
- skipping model updates for the same artifact more than once
- finding the code clearer than the model during review/debugging

**Also do Y**
- either repair the model immediately
- or delete/replace the model artifact in the same cleanup slice

**To get Z effect**
- avoid architecture-doc theater
- keep only models that earn maintenance cost

**Policy**
For this repo, stale models are worse than no models.

---

## Short version

- runtime-flow change -> update sequence/trust model
- authority-boundary change -> update C4-lite and/or trust notes
- non-trivial review -> explicitly confirm model matches, update it, or remove it
- repeated drift -> delete the model rather than pretending we maintain it
