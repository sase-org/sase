---
create_time: 2026-05-23 14:34:43
status: done
prompt: sdd/prompts/202605/workflow_plan_step_stuck_running.md
---
# Fix Plan-Step Stuck at RUNNING After EPIC/TALE/LEGEND Approval

## Symptom

In the user's `sase ace` snapshot, an epic-approved family root has both its `1/1-plan` and `1/1-epic` workflow-child
rows showing `(RUNNING)` simultaneously, and the root row's runtime suffix advances by **2s every 1s** instead of the
expected 1s/1s:

```
≡ 🤖 sase (EPIC APPROVED) ×6 −3 @a59                 🏃‍♂️ 11m18s
  └─ 1/1-plan 🤖 main (RUNNING) ◆ @a59-plan           🏃‍♂️ 9m34s
  └─ 1/1-epic 🤖 sase (RUNNING) ◆ @a59-epic           🏃‍♂️ 1m43s
  └─ 1e/1 🐚 diff (DONE) ▼#gh
```

After the user approved the plan as an epic, the `1/1-plan` row should show `(DONE)` with its runtime frozen at the plan
submission timestamp — only `1/1-epic` should still be ticking, and the root should tick at 1s/1s.

## How the 2s/1s root tick arises

`src/sase/ace/tui/models/agent_time.py::_aggregate_runtime` sums the `_RuntimeInterval.elapsed_seconds` of each
`runtime_children` entry that returns a non-None interval. For each tick:

- An active `(RUNNING)` plan child contributes `now - run_start_time` → grows by 1s/s.
- An active `(RUNNING)` epic child also contributes `now - run_start_time` → grows by 1s/s.
- The aggregate elapsed therefore grows by **2s/s**, which is exactly what the user reports.

Once the plan child becomes terminal (frozen at `max(plan_times)`), it contributes a fixed `elapsed_seconds` instead and
only the epic child keeps growing — the root then ticks at the expected 1s/1s.

Conclusion: the runtime-aggregation code is correct. The fault is in the **data feeding it** — the plan child must
become terminal once the family/workflow has progressed past plan approval.

## Why the plan child is stuck at RUNNING

The display status `RUNNING` is produced by `_workflow_step_loaders.py::_load_workflow_agent_steps_for_dir` from the
on-disk marker `prompt_step_plan.json` whose `status` is `"in_progress"`. That marker is written by the planner's
`WorkflowExecutor` and is only transitioned to `"completed"` (or `"failed"`) inside the planner process itself
(`src/sase/xprompt/workflow_executor_steps_prompt.py` and `workflow_executor.py::_save_prompt_step_marker`).

When the user runs `sase plan` to approve, the planner agent is SIGTERM'd. There are three plausible code paths:

1. **Subprocess-style providers (Codex/Claude CLI):** SIGTERM hits the LLM subprocess, the wrapper raises, the
   workflow*executor `except` arm writes `status="failed"` with a SIGTERM error string, and the post-handoff
   `normalize_handoff_interruption_state` (in `src/sase/axe/run_agent_helpers.py:272`) rewrites that to `"completed"`
   for both `workflow_state.json` and `prompt_step*\*.json` markers. This path is currently working.

2. **In-process SDK providers:** SIGTERM kills the Python process before the workflow_executor `except` arm ever runs.
   The marker is left at `"in_progress"` (or `"waiting_hitl"` if the HITL save happened just before the kill).
   `normalize_handoff_interruption_state` early-exits because no `"failed"` SIGTERM marker was found — so the
   `"in_progress"` / `"waiting_hitl"` marker is **never normalized**, and the TUI displays `(RUNNING)` /
   `(WAITING INPUT)` indefinitely.

3. **Plan submission via the `%plan` directive's auto-approve path:** the planner self-submits, `handle_plan_marker`
   runs in the same process, but `_execute_prompt_step`'s post-HITL `save_prompt_step_marker(... COMPLETED ...)` is
   bypassed because the agent re-enters the loop as a follow-up instead of returning normally through the prompt step.

In all of (2)/(3), the planner's `workflow_state.json` and `prompt_step_plan.json` both remain non-terminal even though
the family root has clearly moved on (it shows `EPIC APPROVED` and a fresh follow-up `@a59-epic` is running).

The TUI loader already has a propagation rule for one terminal case:

```python
# _workflow_step_loaders.py
if parent_wf_completed and agent.status == "RUNNING":
    agent.status = "DONE"
```

That only fires when the planner's own `workflow_state.json` reports `"completed"`. In path (2)/(3) above it doesn't,
because the planner's own state was never normalized.

## Root cause, one sentence

The planner's `prompt_step_plan.json` (and surrounding `workflow_state.json`) can be left in a non-terminal status when
the planner exits via plan approval rather than via a caught exception, and neither the data layer nor the TUI loader
recovers from that state for a workflow-child plan row.

## Approach

Fix this at two layers, defense-in-depth:

### 1. Data layer — explicitly finalize the planner artifacts at handoff

Refactor and extend `normalize_handoff_interruption_state` (or add a sibling `finalize_handoff_artifacts_as_completed`)
in `src/sase/axe/run_agent_helpers.py` so that, when called from `handle_plan_marker`, it **unconditionally** marks the
planner's `workflow_state.json` and any non-terminal `prompt_step_*.json` markers as `"completed"` — not only the
SIGTERM-failure subset.

Concretely, after the SIGTERM-specific normalization that already runs, also flip:

- `workflow_state.json` `status` from `"running"` / `"waiting_hitl"` / `"in_progress"` → `"completed"` (clearing `error`
  and `traceback` if present), and any step entries under `steps` with the same non-terminal statuses.
- Each `prompt_step_*.json` marker whose `status` is `"in_progress"` or `"waiting_hitl"` → `"completed"`. Skip markers
  that are already `"completed"` or `"failed"` (a real failure must remain visible).

This is safe because, by the time `handle_plan_marker` runs, the planner has submitted a plan and is handing off — its
own work is genuinely done. The wire-side index update (`update_agent_artifact_index_for_marker_mutation`) already
exists and should be reused.

Touch points:

- `src/sase/axe/run_agent_helpers.py` — new finalize helper + existing normalize function refactor.
- `src/sase/axe/run_agent_exec_plan.py:142` and `:557` — call the new finalize helper alongside (or in place of) the
  existing normalize call when entering plan handoff.

### 2. TUI layer — propagate "family moved past plan" to a stuck plan step

Even with the data fix landed, snapshots loaded for older state (or any future path that bypasses `handle_plan_marker`)
should not show a confusingly RUNNING plan child under an `EPIC APPROVED` / `TALE APPROVED` / `LEGEND APPROVED` /
`PLAN COMMITTED` family root. Add a TUI-side projection:

In `src/sase/ace/tui/models/_loaders/_workflow_step_loaders.py::_load_workflow_agent_steps_for_dir`:

- Additionally read the **parent family root's** `agent_meta.json` (one directory level up from `timestamp_dir`, or
  located via the existing `parent_workflow` linkage already exposed to the loader) and check `plan_approved == true`
  with a `plan_action` in `{epic, tale, legend, commit}`.
- When that condition holds and a step has `step_name == "plan"` (or `role_suffix` canonicalises to
  `PLAN_CHAIN_PLAN_SUFFIX`) with a non-terminal display status, override the display status to `"DONE"` for that row.

This mirrors the existing `parent_wf_completed`/`parent_wf_failed` override blocks and keeps the runtime aggregation
correct (`_is_planner_phase_row` and `_row_runtime_terminal_time` already freeze planner rows at `max(plan_times)` once
their status is in `_PLAN_RUNTIME_TERMINAL_STATUSES`).

Touch points:

- `src/sase/ace/tui/models/_loaders/_workflow_step_loaders.py` — extended parent-state reading and status override.
- Mirror the same override in the wire-side loader (`_workflow_snapshot_loaders.py`) so live snapshot mode behaves
  identically.

### 3. Regression coverage

Add focused tests under `tests/ace/tui/widgets/` and `tests/` (mirroring `test_agents_tab_finalize_plan.py` and
`test_agent_list_runtime_*.py`):

1. **Data layer:** a planner artifacts dir with `workflow_state.status="in_progress"` and a `prompt_step_plan.json` with
   `status="in_progress"` → after calling the new finalize helper, both become `"completed"`; an existing `"failed"`
   marker with a non-SIGTERM error is **not** touched.
2. **TUI layer:** load a workflow step row with marker `status="in_progress"`, `step_name="plan"`, family-root
   `agent_meta.plan_approved=true, plan_action="epic"` → loader produces `display_status="DONE"`.
3. **Runtime aggregation:** root with one DONE plan child (frozen at `plan_times`) + one RUNNING epic child →
   `_aggregate_runtime` returns an active interval that ticks by exactly the epic child's rate (1s/1s), not 2s/1s.
4. **Regression guard for prior fix (`workflow_child_runtime_ticking.md`):** a workflow-child plan with no parent
   plan-approval signal still ticks live and does not freeze prematurely.

## Validation

- Run the targeted runtime / loader tests first.
- Run `just install` (workspace may be stale per memory/short/build_and_run.md).
- Run the required `just check` after edits.
- Optionally re-launch `sase ace` against a live family with `EPIC APPROVED` status and observe the root suffix ticks at
  1s/1s while the plan child stays frozen at `plan_times`.

## Non-Goals

- No Rust core change. Per `memory/short/rust_core_backend_boundary.md`, this is a TUI/presentation and Python-side
  artifact lifecycle concern — the wire layer just needs the same enrichment as the filesystem path.
- No change to how `plan_times`, `code_time`, or `run_start_time` are populated.
- No general redesign of `_SEGMENTED_FOLLOWUP_RUNTIME_STATUSES` or `_is_planner_phase_row`; the existing gates already
  do the right thing once the plan row's status is terminal — we just need to make it terminal.
- No retroactive cleanup of already-stuck artifacts on disk beyond what the next handoff naturally rewrites.
