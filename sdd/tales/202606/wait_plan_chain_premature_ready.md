---
create_time: 2026-06-07 08:55:25
status: done
prompt: sdd/prompts/202606/wait_plan_chain_premature_ready.md
---
# Plan: Stop wait-dependencies from resolving on an unfinished plan chain

## Problem / Product Context

Agent `3j.f1` failed. Its prompt was:

```
#gh:bob-cli #fork:3j %w:3j Can you now help me fix every existing daily note ... #plan
```

So `3j.f1` was supposed to (a) **wait** for agent `3j` (`%w:3j`) and (b) **fork** `3j`'s chat (`#fork:3j`). It failed
with:

```
Waiting for agents: 3j
All dependencies satisfied, proceeding with workflow   <-- fired too early
⚠️ wait_chats: no done agent found for '3j' — skipping
RuntimeError: No agent with chat history found for: 3j  <-- fork then crashes
```

Timeline (from the artifacts):

- `12:31:41` — `3j` (`--plan`, a plan-chain **root**) starts.
- `12:36:19` — `3j` submits its plan and its `--plan` process **exits** (pid now dead). It writes a **completed**
  `workflow_state.json` + completed `prompt_step_*.json` markers, but **never writes `done.json`** (this is the normal
  plan-chain "handoff": the implementation generation is supposed to run later).
- `12:36:24` — `3j.f1`'s wait barrier is released (`wait_completed_at`) — only **5s** after plan submission, before any
  implementation generation existed.
- `12:36:38` — `3j.f1` runs `#fork:3j`, which needs a _finished_ `3j` and crashes.

The user's diagnosis is correct: **`3j.f1` was launched too soon** — it should not have started until `3j` actually
finished. The `#fork` crash is only a downstream _symptom_; the real defect is that the `%w:3j` wait was declared
satisfied while the `3j` plan chain was still in flight.

## Root Cause

`%w:<name>` waiters poll for `ready.json`, which is written by the wait-resolution chop script
`src/sase/scripts/sase_chop_wait_checks.py`. That script decides a dependency is satisfied via
`_WaitDependencyIndex.is_resolved(name)`, which relies on `_artifact_is_resolved(...)`:

```python
def _artifact_is_resolved(artifact_dir, meta, outcome):
    if outcome is not None:                       # done.json present
        return outcome == "completed"
    if not is_plan_chain_artifact_meta(meta):
        return False
    return _completed_handoff_workflow_state(artifact_dir)   # <-- the trap
```

The `_completed_handoff_workflow_state` branch (added in commit `aaf3ec8a7`, "fix: resolve completed plan handoff wait
deps") exists for a **legitimate** case: an _intermediate_, already-superseded plan-chain phase (e.g. a feedback round
`33.r1--2`) that finalizes via `workflow_state.json` without a `done.json` should not **block** a family whose **newest
generation already has a terminal `--code` `done.json`**. In that scenario the family genuinely finished; the handoff
artifact is just "don't block me."

The bug: that "completed handoff = resolved" signal is being used as the **sole** basis for satisfaction. In the `3j`
case the **entire family is just the `--plan` root** — there is **no terminal `done.json` anywhere** in the family yet.
`family_candidate`, `workflow_candidate`, and `named["3j"]` all collapse to that single root, all report
`is_resolved=True` purely from the completed handoff state, so `ready.json` is written and the waiter proceeds against
an unfinished chain.

Confirmed against the live artifacts: `3j` (`20260607083133`) has `role_suffix:"--plan"`, `agent_family:"3j"`, every
`prompt_step_*.json` and `workflow_state.json` = `completed`, and **no `done.json`**; its process is dead. There is no
other `3j`-family artifact.

## Fix (high-level design)

Make the wait resolver treat a completed handoff state as **"does not block"** but **never as "complete by itself."** A
dependency is satisfied only when the resolving generation contains at least one artifact with a real terminal
`done.json` (outcome `completed`).

Concretely, in `src/sase/scripts/sase_chop_wait_checks.py`:

1. **Track a second flag `is_done`** (a genuine terminal `done.json` with outcome `completed`) alongside the existing
   `is_resolved` ("does not block") on the candidate dataclasses `_WaitCandidate`, `_ArtifactCandidate`, and
   `_FamilyCandidate`. Populate it in `_WaitDependencyIndex.add(...)` from the `done.json` outcome
   (`is_done = outcome == _SUCCESS_OUTCOME`).

2. **Require a real `done` in the resolving generation:**
   - `family_candidate` / `workflow_candidate`: keep `is_resolved = all(members is_resolved)` (intermediates still don't
     block) **and** set `is_done = any(members is_done)` over the same root+generation set (and the legacy-recovery
     sets).
   - `is_resolved(name)`: pick the latest candidate by timestamp and return `latest.is_resolved and latest.is_done`
     instead of just `latest.is_resolved`. For the `named` path this reduces to "must be genuinely done" (a terminal
     `done.json` always implies `is_resolved`), which is exactly right for a `--plan` root that only handed off.

This is surgical and preserves every intended behavior:

- Intermediate handoff phase with no `done.json`, superseded by a `--code` `done.json` → still resolves (the generation
  has `any(is_done)`).
- Failed/killed `done.json` → still blocks (`is_resolved` already False).
- Plain non-plan-chain agent with `done.json` completed → still resolves (`is_done == is_resolved` there).
- **New:** a `--plan` root that merely completed its handoff with no terminal `done.json` anywhere in the family →
  **does not resolve**; the waiter keeps waiting until the chain actually finishes (the existing 24h wait timeout
  remains the backstop).

No change is needed to `agent_chat_from_name.py` / `#fork`: once the waiter only proceeds after `3j` is truly done,
`#fork:3j` resolves via `done.json`'s `response_path` as designed.

## Files to change

- `src/sase/scripts/sase_chop_wait_checks.py` — add `is_done` tracking and the `is_resolved AND is_done`
  (generation-level `any(is_done)`) requirement described above.

## Tests

Add to `tests/test_axe_chop_wait_checks.py`:

- **New regression test** reproducing `3j`: a single plan-chain `--plan` root (`role_suffix="--plan"`,
  `agent_family`/`workflow_name` set, **no `done.json`**) with a completed `workflow_state.json` (via the existing
  `_write_workflow_state` helper) and a waiter on its base name. Assert **`ready.json` is NOT written**. (Fails before
  the fix, passes after.)

Confirm the existing suite still passes unchanged, especially:

- `test_completed_plan_chain_handoff_without_done_resolves_family_dependency` (root + `--code` both have `done.json` →
  still resolves),
- `test_successful_plan_family_dependency_resolves`,
- `test_successful_workflow_name_dependency_resolves`,
- `test_completed_named_agent_success_path_writes_ready`,
- the `*_blocks_*` handoff/incomplete tests.

## Verification

- `just install` (ephemeral workspace), then `just check`.
- Targeted: `pytest tests/test_axe_chop_wait_checks.py`.

## Out of scope / notes

- The downstream `#fork` crash and the `wait_chats: no done agent found ... — skipping` warning are symptoms of the
  premature launch; they resolve once the wait barrier is correct. No `agent_chat_from_name.py` change is planned.
- If a plan is approved but its implementation generation is never launched, the waiter will (correctly) wait until the
  24h `_WAIT_MAX_TIMEOUT` — that is the intended "wait for it to finish" behavior, not a regression. Flagging in case
  the user considers a separate, smaller wait-timeout for plan-chain deps a desirable follow-up.
