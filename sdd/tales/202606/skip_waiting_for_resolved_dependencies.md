---
create_time: 2026-06-19 13:41:18
status: done
prompt: sdd/prompts/202606/skip_waiting_for_resolved_dependencies.md
---
# Plan: Skip WAITING when a `%wait:` dependency already finished

## Problem

When an agent `foo` is launched with `%wait:bar`, it shows as **WAITING** on the Agents tab for a few seconds even when
`bar` had already finished _before_ `foo` was ever launched. We want `foo` to start running immediately in that case,
without any WAITING flicker — and without hurting TUI performance.

## Root cause

The wait barrier runs inside the agent subprocess in `src/sase/axe/run_agent_wait.py::wait_for_dependencies()`. For a
named-dependency wait it unconditionally:

1. Writes `waiting.json` (lines 77-89). The TUI's meta-enrichment turns the presence of `waiting.json` into the
   `WAITING` status (`src/sase/ace/tui/models/_loaders/_meta_enrichment.py`), so WAITING is shown the instant this file
   exists.
2. Polls for `ready.json` every `_WAIT_POLL_INTERVAL = 2s` (lines 99-111). The agent **never checks dependency
   resolution itself**; it just blocks until `ready.json` appears.
3. `ready.json` is only written by the out-of-process lumberjack chop `src/sase/scripts/sase_chop_wait_checks.py`, which
   scans every project's `waiting.json` markers on its own schedule, evaluates resolution via
   `_WaitDependencyIndex.is_resolved()`, and writes `ready.json` when satisfied.

So even when `bar` is already complete, `foo` must wait for: (a) the next chop sweep to write `ready.json`, plus (b) its
own up-to-2s poll to observe it. That round trip is the "few seconds" of WAITING the user sees. There is no fast path
for "dependencies are already satisfied at launch."

## Goal / approach

Add an **eager, one-shot resolution check at the top of the named-dependency branch** of `wait_for_dependencies()`. If
every `wait_names` entry is already resolved (using the _exact same_ resolution logic the chop uses) and there is no
time-based floor still pending, skip writing `waiting.json` and skip the poll-for-`ready.json` loop entirely — the agent
proceeds straight to RUNNING, just like a no-wait launch.

If the eager check says "not all resolved" (for any reason), we fall through to today's exact slow path: write
`waiting.json`, poll, let the chop resolve it when `bar` finishes later. **The eager check is a pure optimization and a
pure short-circuit of the existing path** — it can only ever _skip_ a wait that the chop would also have released, never
release one the chop would not.

### Why this is the right layer

- The fix lives entirely in the **agent subprocess** (`run_agent_wait.py`). It does not touch the TUI refresh loop,
  marker scanning, rendering, or any timer. In fact it _reduces_ TUI work for this case: when deps are already resolved,
  `waiting.json` is never written, so the TUI never renders a WAITING row that immediately flips to RUNNING. **TUI
  performance is strictly neutral-to-better.**
- It reuses the canonical resolution logic instead of inventing a second, drift-prone definition of "done."

## Design

### 1. Extract the resolution logic into a shared module (refactor, no behavior change)

Today the resolution machinery lives privately inside `src/sase/scripts/sase_chop_wait_checks.py`:

- `_WaitDependencyIndex` (+ `_WaitCandidate`, `_ArtifactCandidate`, `_FamilyCandidate`) and its `add()` /
  `family_candidate()` / `workflow_candidate()` / `is_resolved()` methods.
- Helpers: `_done_outcome`, `_artifact_is_resolved`, `_completed_handoff_workflow_state`, `_has_failure_fields`,
  `_has_blocking_prompt_step_marker`, `_family_base_from_meta`, `_read_json_dict`.

Move these into a new shared module — proposed `src/sase/core/wait_dependency_resolution.py` (verified import-safe:
`sase.core` does not import `sase.axe`/`sase.scripts`, and `sase.plan_chain` does not import `sase.core`, so no cycle).
Expose:

- `WaitDependencyIndex` (the renamed-public index) with a `build(...)` classmethod or a free
  `build_wait_dependency_index(project_name, *, projects_root=None)` that scans one project's `ace-run` artifacts via
  `iter_agent_artifact_dirs`.
- `dependencies_resolved(index, wait_names) -> bool` — the `all_done` loop currently inline in the chop's `main()`
  (lines 347-352).

`sase_chop_wait_checks.py` then imports these and keeps its global multi-project sweep in `main()` unchanged. This
refactor must be behavior-preserving; the existing chop tests (`tests/test_axe_chop_wait_checks.py`) are the guard.

### 2. Add the eager fast path in `wait_for_dependencies()`

At the start of the `if wait_names:` branch, before writing `waiting.json`:

```
fast_path = (
    duration is None
    and wait_until is None
    and _all_dependencies_already_resolved(wait_names, artifacts_dir)
)
```

- `_all_dependencies_already_resolved` builds the index **scoped to the current project** (derived from `artifacts_dir`,
  or passed in as `project_name`) and returns `dependencies_resolved(index, wait_names)`.
- If `fast_path`: print a short "Dependencies already satisfied, proceeding without waiting" line, call
  `_record_wait_completed_at(...)` for downstream consistency, and skip the `waiting.json` write + poll loop. No marker
  is written, so no `update_agent_artifact_index_for_marker_mutation` call and no cleanup are needed.
- Otherwise: unchanged slow path.

**Scope:** only fire the fast path when there is **no `duration` and no `wait_until` floor**. With a time floor the
agent genuinely must keep waiting and showing WAITING is correct, so those paths are left exactly as they are. This
matches the user's reported case (`%wait:bar`, no duration) and keeps the change minimal.

The call site (`run_agent_runner.py:365`) already has `project_name` in scope, so passing the project explicitly into
`wait_for_dependencies()` is the cleanest way to give the eager check its scan scope (avoids re-deriving the project
from the path). Everything after `wait_for_dependencies()` returns — deferred-workspace claim,
`resolve_wait_chat_paths`, repeat-stop detection — is unchanged.

### Resolution scope: current project (recommended)

Build the eager index from the **current project only**. Wait dependencies refer to sibling agents in the same project,
so this is where `bar` lives, and a single-project scan keeps the startup cost tiny. This is _safe_: if a dependency
can't be found/resolved in the current project's scan, the eager check returns `False` and we fall to the slow path
exactly as today — the chop's global sweep still resolves it. The only thing a narrow scope can lose is the
_optimization_ for an (unusual) cross-project wait, never correctness.

(Alternative considered: replicate the chop's all-projects scan for byte-identical semantics. Rejected as the default
because it adds a global scan to every waiting agent's startup — including agents whose deps are _not_ yet ready, where
the scan is wasted — for a negligible correctness gain over same-project scope.)

## Performance considerations (explicitly requested)

- **TUI:** untouched. No new timers, intervals, scans, or render work. The resolved-dependency case now produces _fewer_
  marker writes and _no_ transient WAITING row, so the TUI does strictly less, never more.
- **Agent startup:** adds one project-scoped artifact scan when an agent has a named `%wait`. This is one-shot (not a
  loop), scoped to a single project, and reuses the same per-artifact JSON reads the chop already performs. It trades a
  multi-second WAITING round trip for a sub-second local scan — a net latency win even when it has to fall through to
  the slow path.
- **Chop:** unchanged cadence and cost; it simply imports the now-shared helpers.

## Correctness / safety

- Reusing the chop's exact `is_resolved` logic guarantees the eager check cannot release a wait the chop would hold (no
  new false-positive "done" risk).
- Time floors (`duration`, `wait_until`) are deliberately excluded from the fast path, so floor semantics are unchanged.
- Kill-during-wait, `wait_completed_at` durability, and marker-index mutation behavior on the slow path are all left
  intact.

## Testing

- **New** `tests/test_run_agent_wait.py` cases:
  - Deps already resolved (chop-style completed artifact present in the scanned project) ⇒ `wait_for_dependencies`
    writes **no** `waiting.json`, performs no poll, records `wait_completed_at`, and returns promptly.
  - Deps **not** resolved ⇒ falls back to the slow path (writes `waiting.json`, polls for `ready.json`) — i.e. current
    behavior preserved.
  - Fast path is **not** taken when `duration`/`wait_until` is set even if deps are resolved.
- **Refactor guard:** `tests/test_axe_chop_wait_checks.py` must pass unchanged after the extraction; add a small test
  asserting the eager check and the chop resolve the same fixtures identically (shared-module parity).
- Run `just check` (requires `just install` first in this ephemeral workspace).

## Files touched

- `src/sase/axe/run_agent_wait.py` — eager fast path; accept project scope.
- `src/sase/axe/run_agent_runner.py` — pass `project_name` into the wait call.
- `src/sase/scripts/sase_chop_wait_checks.py` — import shared helpers instead of defining them privately.
- `src/sase/core/wait_dependency_resolution.py` — **new** shared module.
- `tests/test_run_agent_wait.py`, `tests/test_axe_chop_wait_checks.py` — tests.

## Open decision: Python extraction now vs. Rust core

`memory/rust_core_backend_boundary.md` says shared backend/domain behavior belongs in the Rust `sase-core` repo.
Wait-dependency _resolution_ is arguably such backend logic, but today it lives entirely in Python (the chop), and the
Rust side (`agent_scan/wire.rs`) only models the marker wire types for TUI scanning — it does not compute resolution.
Porting the full resolution semantics (plan-chain handoff state, family/workflow candidate selection, terminal-step
checks) to Rust is a sizeable, separate effort.

**Recommendation:** do the pragmatic Python extraction described above now (keeps the eager check and the chop on one
shared definition with no duplication), and treat "move wait-dependency resolution into Rust `sase-core`" as a follow-up
if/when another frontend needs it. Flagging this so you can redirect to the Rust route if you'd prefer the canonical
home immediately.
