---
create_time: 2026-06-22 10:29:41
status: done
prompt: sdd/prompts/202606/freeze_approved_plan_runtime.md
---
# Plan: Freeze runtime for `PLAN APPROVED` / `TALE APPROVED` rows

## Problem

On the Agents tab, the runtime suffix of a sticky-approved planner row keeps incrementing even though the planner
("plan") agent was killed right after submitting its plan. Because a family root aggregates the runtimes of its
children, the root row then advances **2 seconds every wall-clock second**: once for the still-"running" planner child
and once for the live coder child.

Concretely, for a tale-approved family with a running coder (`03e.cdx.f1`):

| Row                 | Status          | Runtime now (wrong)    | Desired                   |
| ------------------- | --------------- | ---------------------- | ------------------------- |
| `03e.cdx.f1` (root) | `WORKING TALE`  | ticks **+2s/s**        | ticks **+1s/s**           |
| `03e.cdx.f1--plan`  | `TALE APPROVED` | ticks **+1s/s** (live) | **frozen at plan submit** |
| `03e.cdx.f1--code`  | `WORKING TALE`  | ticks +1s/s            | ticks +1s/s (unchanged)   |

## Root-cause diagnosis

Runtime display is computed entirely in Python TUI presentation code in `src/sase/ace/tui/models/agent_time.py` (no
`sase-core` involvement — the elapsed value is derived locally from already-shared timestamps for display only).

The recent "sticky planner" status work changed the planner child's status from `DONE` to the sticky `PLAN APPROVED` /
`TALE APPROVED`. Two facts about the runtime helpers then flipped the planner row from "frozen" to "live":

1. **The planner-phase freeze no longer triggers.** `_row_runtime_terminal_time()` freezes a row at its plan submission
   time (`max(plan_times)`) when `_is_planner_phase_row()` is true. But `_is_planner_phase_row()` bails out early when
   `agent.stop_time is None and agent.status not in _PLANNER_PHASE_ENDED_STATUSES`. A killed `--plan` workflow step has
   **no `stop_time`** (its "doneness" is inferred from plan submission/approval, not a process stop), and the new
   approved statuses are **not** members of `_PLANNER_PHASE_ENDED_STATUSES` (`DONE` was). So the freeze is skipped and
   no terminal time is computed.

2. **The approved status is treated as actively running.** `_SEGMENTED_FOLLOWUP_RUNTIME_STATUSES`
   (`= ACTIVE_PLAN_HANDOFF_STATUSES`) includes `PLAN APPROVED` / `TALE APPROVED`. With no terminal time set, the
   `--plan` workflow step falls into the "active workflow agent step" branch of `_leaf_runtime_interval()` and the
   matching branch of `runtime_suffix_ticks()`, so it reports a live, ticking runtime.

The root row uses `_aggregate_runtime()` (sum of its runtime children). With the planner child live and the coder child
live, the sum advances 2s/s. (Before the status change, the planner child was `DONE`, which _is_ terminal, so it froze
and the root advanced 1s/s — see the existing regression test
`test_workflow_root_aggregate_ticks_at_1s_per_1s_with_done_plan_child`.)

This was reproduced directly: the `--plan` step rendered `(None, '19m50s') -> (None, '19m51s')` (live), and the root
rendered `29m50s -> 29m52s` (+2s/s).

## Design

A row that displays `PLAN APPROVED` / `TALE APPROVED` has finished its planning work — the plan was submitted and
approved, and the planner agent was killed. Its runtime must therefore **freeze at the plan submission time**, the same
anchor already used for completed planner rows (`DONE` / `PLAN DONE` / `TALE DONE`).

This is consistent and complete in the new status model: the only rows that ever display an approved status are
planner/root rows (sticky-approved or mirroring the planner during the pre-coder gap). The coder always displays
`WORKING PLAN` / `WORKING TALE` (or `… DONE`) while it runs, never an approved status, so coder rows keep ticking.

The cleanest mechanism is a single rule keyed on the displayed status plus the presence of a submitted plan:

> **If `status ∈ {PLAN APPROVED, TALE APPROVED}` and the row has `plan_times`, its runtime is terminal, anchored at
> `max(plan_times)`.**

Gating on `plan_times` keeps coder rows (which never carry `plan_times`) ticking and leaves all non-plan-submitting rows
untouched.

With the planner child frozen, the root's aggregate becomes `frozen planner + live coder = +1s/s`, and the pre-coder-gap
root (mirroring the approved planner) also freezes — both correct.

## Implementation

All changes are in `src/sase/ace/tui/models/agent_time.py`.

### Change A — Freeze approved-plan rows in the runtime interval

In `_row_runtime_terminal_time()`, add a branch (placed alongside the existing `_is_planner_phase_row` branch, i.e.
**before** the `stop_time` branch so plan-submission time wins over any later stop, matching the existing planner
convention): if `agent.status ∈ APPROVED_PLAN_STATUSES` and `agent.plan_times`, return `max(agent.plan_times)`.

`_leaf_runtime_interval()` already short-circuits to a frozen interval whenever `_row_runtime_terminal_time()` returns
non-`None`, so this alone freezes `compute_row_runtime()` for approved planner/root rows and never reaches the
segmented/active branches.

### Change B — Approved-plan rows do not tick

In `runtime_suffix_ticks()`, add a guard (after the `runtime_children` recursion and the `stop_time` check, before the
segmented/active branches): if `agent.status ∈ APPROVED_PLAN_STATUSES` and `agent.plan_times`, return `False`.

This is required because `runtime_suffix_ticks()` computes tickiness independently of `_row_runtime_terminal_time()`.
The guard sits after the child recursion so a root still reports ticking when its live coder child ticks, and the render
layer (`_agent_list_render_layout.build_runtime_suffix`) then drops the live "🏃" marker for the frozen approved row,
rendering a clean finished suffix (e.g. `13:14:53 · 4m46s`) instead of `🏃 5m51s`.

Import `APPROVED_PLAN_STATUSES` from `sase.agent.status_buckets`.

### Why this is sufficient and contained

- A killed `--plan` workflow step (`TALE APPROVED`, `stop_time=None`, has `plan_times`) → frozen at `max(plan_times)`,
  `ticks=False`. Verified: `(('', '09:05:00'), '4m50s')` constant across ticks.
- Synthetic planner rows and a childless root mirroring the approved planner are handled by the same rule.
- Root aggregate (frozen planner + live coder) advances exactly +1s/s. Verified: `14m50s -> 14m51s`.
- Coder rows (`WORKING …`, or a transient `TALE APPROVED` coder with no `plan_times`) are untouched — they keep ticking.
  Verified: standalone coder `2m05s`, `ticks=True`.
- A still-`RUNNING` planner that has already submitted a plan keeps ticking (agent still alive) — unchanged, since the
  rule is keyed on the approved status, not on `plan_times` alone.
- `DONE` / `PLAN DONE` / `TALE DONE` planner rows still freeze via the existing `_PLAN_RUNTIME_TERMINAL_STATUSES` path —
  unchanged.
- `EPIC APPROVED` / `LEGEND APPROVED` are deliberately out of scope (`APPROVED_PLAN_STATUSES` is only PLAN/TALE), and
  epic/legend/commit planner children still display `DONE`, so they keep their current frozen behavior.

No change is needed to `_SEGMENTED_FOLLOWUP_RUNTIME_STATUSES`, `_PLANNER_PHASE_ENDED_STATUSES`, or the segmented
interval/`_is_active_approved_followup_coder` logic; the terminal-time short-circuit and the tick guard cover every
approved-plan case, and the segmented path remains available for `WORKING …` rows.

## Tests

Update the tests that encode the obsolete "an approved row shows a live, segmented runtime" behavior (this modeled the
pre-sticky root that itself carried the approved label). All live in `tests/ace/tui/widgets/`:

- `test_agent_list_runtime_ticks.py::test_runtime_suffix_ticks_plan_approved_with_segmented_parent_times` → an approved
  row with `plan_times` now reports `ticks is False`. Rename to reflect "frozen".
- `test_agent_list_runtime_planning.py::test_plan_approved_plan_suffix_runtime_is_segmented` → now frozen:
  `ts == ("", "13:14:53")`, `elapsed == "4m46s"`, `runtime_suffix_ticks is False`. Rename to reflect the frozen
  invariant.
- `test_agent_list_runtime_planning.py::test_compute_row_runtime_plan_approved_uses_segmented_parent_times` → now
  frozen: `ts == ("", "13:16:00")`, `elapsed == "5m53s"`. Rename accordingly.
- `test_agent_list_runtime_patching.py::test_patch_active_runtime_rows_advances_plan_approved_parent_times` → an
  approved row with `plan_times` is now frozen, so it is **not** patched as an active row (no per-second advance).
  Reframe as "skips frozen approved-plan row" (assert the suffix shows the frozen finished form and does not advance
  between ticks).
- `test_agent_list_runtime_rendering.py::test_format_agent_option_plan_approved_active_suffix_has_running_marker` → now
  renders the frozen finished suffix `"13:14:53 · 4m46s"` (no "🏃" live marker, still no "✋"). Rename to reflect
  "frozen suffix has no running marker".

Add regression coverage in `test_agent_list_runtime_planning.py`:

- **The reported bug, single row:** a `--plan` workflow agent step with `status="TALE APPROVED"`, `stop_time=None`, and
  `plan_times` freezes at `max(plan_times)` with `runtime_suffix_ticks is False`.
- **The reported bug, aggregate:** a family root with
  `runtime_children = [approved planner (TALE APPROVED, plan_times, stop_time=None), running coder]` advances exactly
  **+1s/s** between two 1-second-apart `now` values (mirrors the existing `…_with_done_plan_child` test but with the
  planner carrying the sticky approved status), guarding against the 2s/s regression.

The unrelated approved-row tests that already use the child-aggregate path or carry no `plan_times`
(`test_compute_row_runtime_aggregates_completed_and_active_children`,
`test_workflow_coder_child_with_tale_approved_ticks_from_run_start`, `test_compute_row_runtime_standalone_coder_active`,
the `…ordering` collision test, and `test_format_agent_option_aggregate_parent_uses_child_sum`) are unaffected and must
keep passing as-is.

## Validation

- `just install` then `just check` (ruff + mypy + fast tests).
- `just test-visual`: the `agents_plan_handoff_status_colors_120x40` snapshot is expected to pass **without
  regeneration** — its approved rows have no `plan_times`/`run_start_time`, so they render no runtime suffix and are
  unaffected by this change.
- Manual smoke in `sase ace`: approve a tale/standard plan with a running coder; confirm the `--plan` row's runtime
  stops advancing (frozen at plan submission) and the root row advances by exactly one second per second.

## Scope / boundary

- Pure Python TUI presentation layer; **no `sase-core` / `sase_core_rs` changes** — only the locally-computed runtime
  suffix changes, keyed on already-shared status strings and timestamps (per the Rust-core boundary rule).

## Out of scope

- Status strings, status colors, and the planner/root/coder status assignments (already settled by the prior
  sticky-planner work).
- `EPIC APPROVED` / `LEGEND APPROVED` / commit-plan runtime behavior (unchanged).
- Any restructuring of the segmented-followup runtime mechanism beyond the additions above.
