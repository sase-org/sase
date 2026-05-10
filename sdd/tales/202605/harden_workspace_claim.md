---
create_time: 2026-05-10 12:44:40
status: done
---
# Harden Workspace Claiming and Surface Claim-Failure Diagnostics

## Problem

`~/.sase/axe/error_digests/digest_20260510_114855.txt` shows two consecutive failures of axe lumberjack `run_every`
running chop `sase_fix_just`:

```
Error:      Failed to claim workspace #107
Traceback:  NoneType: None
```

Two errors, ~1 minute apart. The chop is configured with `run_every: 60m` but the lumberjack ticks every 60s — the 60m
gate uses the chop-timestamps map, which gets updated on success **and** on failure (see `lumberjack.py:421`). So the
two errors here are **separate ticks where the gate was open**, not a tight retry loop. Either way, two facts about the
digest are wrong:

1. The error message is uninformative — "Failed to claim workspace #107" with no reason.
2. The traceback is the literal string `"NoneType: None"`, which is a known Python footgun: it's what
   `traceback.format_exc()` returns when called outside an active `except` block.

At read time the project's `RUNNING:` field in `~/.sase/projects/sase/sase.gp` did **not** contain #107, so the slot
wasn't permanently stuck — the failures were transient. But because the diagnostic surface throws away "why", we can't
tell from the digest whether the cause was a TOCTOU race with another launcher, a Rust validation rejection, an IO/lock
error, or something else. That is the real bug to fix: **the system silently drops the information needed to diagnose
its own failures.**

## Root Cause Analysis

### Symptom A — uninformative error message

`claim_workspace()` in `src/sase/running_field/_operations.py` swallows two distinct failure modes into a bare
`return False`:

```python
try:
    with changespec_lock(project_file):
        ...
        plan = plan_claim_workspace_from_content(content, ...)
        outcome = dict(plan["outcome"])
        if not bool(outcome["success"]):
            return False                       # (1) Rust rejected — reason is in `outcome` but discarded
        ...
        return True
except Exception:
    if attempt < max_retries:
        time.sleep(0.5)
        continue
    return False                               # (2) Python exception — fully swallowed
```

Then `_claim_spawned_child` in `src/sase/agent/launch_spawn.py:207-216` raises a featureless
`RuntimeError(f"Failed to claim workspace #{claim_num}")` with none of that context.

### Symptom B — TOCTOU race window

`src/sase/agent/launch_executor.py:_resolve_slot_workspace` (line 274) calls `get_first_available_axe_workspace()` to
pick a number, but the actual `claim_workspace()` call happens inside the spawned child's `_claim_spawned_child`
callback (`launch_spawn.py:207`). Between those two events:

- The prepared launch is built (Rust round-trip).
- The detached subprocess is spawned (more Rust work, fork/exec).
- The child runs the callback which finally claims.

That's a wide window during which any other process choosing the same project file can pick the same number and claim
first. An atomic `claim_next_axe_workspace()` already exists at `src/sase/running_field/_operations.py:342` — it's just
not used in this path.

### Symptom C — `"NoneType: None"` traceback

`src/sase/axe/lumberjack.py:_handle_error` (line 437):

```python
"traceback": tb if tb is not None else traceback.format_exc(),
```

The `format_exc()` fallback runs at log time, which is outside any active `except` block — `sys.exc_info()` is
`(None, None, None)`, and `format_exc()` then literally returns `"NoneType: None\n"`. The `_ChopResult.traceback` field
is `None` whenever a result was constructed in a non-`except` path:

- Line 266-272: "Chop script not found" (manually-constructed `RuntimeError`)
- Line 296-306: "exit code N: stderr" (manually-constructed `RuntimeError`)

The agent-chop path (line 414-424) does set `traceback=traceback.format_exc()` from inside the `except`, so in principle
it should be populated. The fact that the digest still shows `"NoneType: None"` for an agent chop suggests one of:

- A subtle bug where the agent-chop result reaches `_handle_error` with `traceback=None` despite the code that intends
  to set it (worth auditing for any pyo3/FFI weirdness that clears `sys.exc_info()` before `format_exc()` runs).
- More likely: the `_handle_error` fallback is itself the bug, and we should never rely on a deferred `format_exc()`
  call.

Either way the fix is the same: kill the dangerous fallback and ensure every error-bearing `_ChopResult` carries its own
captured traceback.

### Symptom D — retry loop didn't engage

`_spawn_slot_with_workspace_retry` in `launch_executor.py:193` does have a retry wrapper that catches
`RuntimeError("Failed to claim workspace #...")` and retries up to 6 attempts. But the digest shows the inner message,
not the wrapped "after 6 attempts" message. So either:

- The retry didn't trigger (`_should_retry_workspace_claim` returned False — possible if the chop's `#gh:sase`
  resolution somehow ends up `use_preallocated_workspace`/`is_home_mode`/`deferred_workspace`), or
- The exception bubbled past the retry wrapper without being caught (e.g. wrapped by pyo3 into something whose
  `str(exc)` doesn't start with "Failed to claim workspace #").

Whichever it is, the retry loop is also weak in two ways: no backoff/jitter (immediate same-tick retries lockstep with
other contenders), and the retry predicate keys on a string-prefix match of the exception message — fragile.

### Boundary call-out

Per `memory/short/rust_core_backend_boundary.md`: the **shape** of the claim outcome (success bool + reason string) and
the canonical "Failed to claim workspace #N" message construction live on the boundary between Python and the Rust core
(`sase_core_rs`). The Python wrappers in `running_field/_operations.py` are thin adapters around
`plan_claim_workspace_from_content` and friends. To surface the _reason_ for a Rust-rejected claim, the **Rust outcome
dict** needs to carry an `error` / `reason` field that Python can propagate upward. The Rust crate is at
`../sase-core/crates/sase_core` and ships its bindings as `sase_core_rs`.

The plan below splits work explicitly between the two repos.

## Fix

### Phase 1 — Surface the reason for claim failure (sase-core + this repo)

**Goal:** when a claim fails, the upstream `RuntimeError` and the error digest both contain _why_.

#### Phase 1a — Rust side (`../sase-core/crates/sase_core`)

Update the claim-planning APIs to always populate a human-readable `error` (or `reason`) field in the outcome dict on
rejection:

- `plan_claim_workspace`
- `allocate_and_claim_workspace`
- `plan_transfer_workspace_claim`

Examples of reasons that should be surfaced verbatim:

- `"workspace #107 already claimed by pid 12345 (workflow=ace(run)-...)"`
- `"workspace #107 outside allowed range 100-199"`
- `"all axe workspaces 100-199 are claimed"`
- `"transfer source claim not found: workspace #107 from pid 12345"`

Update bindings (`sase_core_rs`) and Rust tests. The `outcome` dict is already a HashMap-shaped structure on the wire,
so this is additive and doesn't break any callers that ignore the field.

#### Phase 1b — Python side (this repo)

- Change the signature of the four primary claim helpers in `src/sase/running_field/_operations.py` from `-> bool` to
  `-> ClaimResult` (a frozen dataclass with `success: bool` and `error: str | None`):
  - `claim_workspace`
  - `release_workspace`
  - `transfer_workspace_claim`
  - `claim_next_axe_workspace` (already raises; keep raises but enrich the message)
- On Rust rejection, propagate the Rust outcome's `error` field. On Python `Exception`, capture `repr(exc)` + traceback
  into the result rather than swallowing.
- Stop swallowing all `Exception`s. Re-raise unexpected exceptions (anything not a known transient like file-not- found
  / lock contention) — those are real bugs we want to see, not silent `False` returns.
- Update **all** call sites in one pass (no compatibility shims):
  - `src/sase/agent/launch_spawn.py` (raises richer `RuntimeError` including reason)
  - `src/sase/workflows/rewind/workflow.py`
  - `src/sase/workspace_provider/plugins/bare_git_submit.py`
  - `src/sase/ace/handlers/reword.py`
  - `src/sase/ace/archive.py`
  - `src/sase/ace/tui/actions/sync.py`
  - `src/sase/ace/tui/actions/rename.py`
  - `src/sase/ace/tui/actions/proposal_rebase.py`
  - `src/sase/axe/run_agent_phases.py`

The call site in `launch_spawn.py:207` becomes:

```python
result = claim_workspace(...)
if not result.success:
    timer.finish(outcome="claim_failed")
    raise RuntimeError(
        f"Failed to claim workspace #{claim_num}: {result.error or 'unknown reason'}"
    )
```

### Phase 2 — Eliminate the TOCTOU race in the spawn flow

**Goal:** make the find-and-claim atomic for the axe-workspace launch path.

Two options, and we should pick **(B2)** because it preserves the existing prepared-launch wire contract and reuses the
already-tested `transfer_workspace_claim` primitive:

- **(B1) Allocate inside the claim_callback.** Pre-prepare the launch with a placeholder `workspace_num=0`, then in
  `_claim_spawned_child` use `claim_next_axe_workspace(child_pid)` to atomically pick + claim. Push the chosen number
  into the spawned child via env var (the child reads it from `SASE_*_WORKSPACE_NUM`). Requires Rust wire changes to
  `prepare_agent_launch` and to anything downstream that reads `workspace_num` before the callback — large blast radius.
- **(B2) Pre-claim with the parent PID, then transfer to child PID.** In `_resolve_slot_workspace` (or a new helper
  called from `_spawn_slot_with_workspace_retry`):
  1. Call `claim_next_axe_workspace(project_file, workflow, pid=os.getpid())` — atomic find+claim under the project
     lock.
  2. Pass the resulting `workspace_num` into the prepared launch as today.
  3. In `_claim_spawned_child`, replace the `claim_workspace()` call with
     `transfer_workspace_claim(from_pid= parent_pid, to_pid=child_pid, ...)` — atomic ownership swap, also under the
     project lock.
  4. If the spawn fails after step 1 but before step 3, release the parent claim in a `finally` (or an
     `on_spawn_failure` hook); the existing `_spawn_slot_with_workspace_retry` already has the structural hook for this.

This keeps the workspace **continuously claimed** from the moment of allocation through to the running child — the same
continuity property the spawn-on-retry flow already relies on.

The `is_home_mode` / `deferred_workspace` / `use_preallocated_workspace` branches of `_resolve_slot_workspace` remain
unchanged.

### Phase 3 — Retry loop hardening

**Goal:** when a claim genuinely loses a race, retry promptly without lockstepping.

In `src/sase/agent/launch_executor.py`:

- Add jittered backoff between attempts in `_spawn_slot_with_workspace_retry`:
  `time.sleep(random.uniform(0.05, 0.25) * attempt)`. Default ceiling 1s.
- Stop predicating retry on `str(exc).startswith("Failed to claim workspace #")` (fragile to message changes from Phase
  1). Either:
  - Introduce a dedicated `WorkspaceClaimError` exception class (raised from `launch_spawn._claim_spawned_child`) that
    the retry wrapper catches by type, or
  - Attach a sentinel attribute (`exc.is_workspace_claim_failure = True`) to the raised RuntimeError. Class-based is
    cleaner; do that.
- Audit why the retry didn't engage in the observed digest. Add an integration test that simulates a Rust-rejected claim
  from inside the spawn callback and verifies `_spawn_slot_with_workspace_retry` retries.
- Verify the FFI path: an exception raised inside the Python `claim_callback` invoked from
  `spawn_prepared_agent_process` should propagate cleanly back to Python with its type intact. There's already a
  regression test (`tests/test_core_agent_launch_wire.py::test_spawn_prepared_agent_process_cleans_up_on_claim_failure`)
  — extend it to cover `WorkspaceClaimError` specifically.

### Phase 4 — Lumberjack traceback capture fix

**Goal:** never emit `"NoneType: None"` to error digests.

In `src/sase/axe/lumberjack.py`:

- `_handle_error`: replace the `format_exc()` fallback with a constant placeholder `"<traceback unavailable>"`. The
  fallback is the bug — there is no scenario where it does the right thing, because it only runs when `tb is None`,
  which means the caller had no active exception context anyway.
- Audit every `_ChopResult(error=...)` construction site:
  - Lines 266-272 ("Chop script not found"), 296-306 ("exit code N") — set
    `traceback="<no python traceback: subprocess error>"` (a script chop's nonzero exit is not a Python exception, so a
    traceback is genuinely unavailable, but say so explicitly rather than emitting `"NoneType: None"`).
  - All other paths already capture `traceback.format_exc()` inside the `except` block — confirm and add a helper
    `_capture_traceback()` to centralize.
- Add a unit test that constructs a `_ChopResult` for each error path and runs `_handle_error` to verify the final
  `error_info["traceback"]` never contains the literal string `"NoneType: None"`.

### Phase 5 — Tests

Add tests in:

- `tests/test_running_field_operations.py` — `ClaimResult` happy path, Rust-rejected path with reason, exception path.
- `tests/test_agent_launch_executor.py` — atomic find-and-claim for spawn flow; retry kicks in on `WorkspaceClaimError`;
  retry exhaustion message includes underlying reason.
- `tests/test_core_agent_launch_wire.py` — extend existing claim-failure cleanup test to cover `WorkspaceClaimError`
  propagation.
- New `tests/test_lumberjack_traceback.py` — `_handle_error` never emits `"NoneType: None"`.

### Phase 6 — Documentation

- Update `memory/short/glossary.md` Retry-chain / spawn-on-retry entry to mention the new pre-claim+transfer flow for
  the regular launch path (so it's clear both flows now use the same atomic primitive).
- Add a one-line note to `memory/short/gotchas.md` about the new `WorkspaceClaimError` and the rule that `format_exc()`
  fallbacks at log time must not exist.

## Open Questions Resolved

1. **B1 vs B2** — Plan picks B2: smaller blast radius, preserves the prepared-launch wire contract, reuses the
   already-shipped `transfer_workspace_claim` primitive.
2. **Signature change for `claim_workspace`** — Plan picks the breaking change (return `ClaimResult` instead of `bool`).
   Repo conventions forbid back-compat shims; we update all callers in the same change.
3. **Apply same diagnostic surface to `claim_next_axe_workspace` and `transfer_workspace_claim`** — Yes, for
   consistency, even though they already raise on failure.
4. **Rust vs Python split** — The Rust outcome enrichment (Phase 1a) lives in `../sase-core`. Everything else is Python
   in this repo. The Python work in Phase 1b can land before the Rust enrichment ships; on the Python side, `error` is
   just `outcome.get("error")` — empty until Rust populates it, which is graceful.

## Verification

Per `memory/short/build_and_run.md`: run `just check` before declaring the work done. Per `memory/short/workspaces.md`:
run `just install` first if working from a freshly-cloned `sase_<N>` workspace.
