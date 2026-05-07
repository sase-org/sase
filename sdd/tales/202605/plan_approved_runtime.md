---
create_time: 2026-05-07 10:30:42
status: done
prompt: sdd/prompts/202605/plan_approved_runtime.md
---
# Plan: Show Runtime for PLAN APPROVED Plan-Chain Agents

## Problem

Some agent statuses represent active work but do not currently render a ticking runtime suffix in `sase ace`. The
concrete example is a root plan-chain agent with status `PLAN APPROVED` and timestamps:

- `BEGIN`: when the planner began
- `PLAN`: when the submitted plan phase ended
- `CODE`: when the coder follow-up began

For this row, `sase ace` should show a live runtime that ticks every second. The runtime should be the sum of:

1. `PLAN - BEGIN`
2. `now - CODE`

This excludes the approval/wait gap between `PLAN` and `CODE`.

## Current Behavior

Runtime display is centralized in `src/sase/ace/tui/models/agent_time.py`.

The existing model supports:

- plain active leaf agents: `RUNNING`, `RETRYING`
- `WAITING` agents after `run_start_time`
- terminal plan rows using `plan_times`
- aggregate workflow rows via `runtime_children`

There is already test coverage for a `PLAN APPROVED` workflow parent whose `runtime_children` contain a completed
planner child and a running coder child. That path works because the runtime is computed from child intervals.

The missing case is a single root plan-chain row with no useful `runtime_children`, but with enough timestamp metadata
on the parent itself:

- `start_time` / `run_start_time` as BEGIN
- `plan_times` as PLAN submissions
- `code_time` as CODE launch
- `status == "PLAN APPROVED"`

For that shape, `_leaf_runtime_interval()` returns `None` because `PLAN APPROVED` is not treated as a leaf active
runtime state.

## Implementation Approach

1. Add a small helper in `agent_time.py` that computes a segmented active plan runtime for statuses that launch a
   code-like follow-up:
   - Start with `PLAN APPROVED`.
   - Consider whether the same behavior should include equivalent active follow-up statuses such as `PLAN COMMITTED`,
     `EPIC APPROVED`, and `LEGEND APPROVED`; keep the initial fix scoped unless existing semantics clearly require the
     broader set.
   - Require `start_time`, at least one `plan_times` entry, and `code_time`.
   - Use `run_start_time or start_time` as BEGIN, matching the existing runtime convention.
   - Use the latest plan timestamp at or before `code_time` if possible; otherwise use the latest plan timestamp.
   - Compute `max(0, PLAN - BEGIN) + max(0, now - CODE)`.
   - Return an active `_RuntimeInterval` with no terminal timestamp.

2. Wire that helper into `_leaf_runtime_interval()` before the generic active-status checks.
   - This gives single-row plan-chain agents a suffix even when they do not have `runtime_children`.
   - Existing aggregate parent behavior should remain unchanged because `_runtime_interval()` already prefers aggregate
     runtime when children contribute.

3. Update `runtime_suffix_ticks()` so the same single-row `PLAN APPROVED` shape is recognized as ticking.
   - The row patcher relies on this to refresh the suffix every second without rebuilding the full list.

4. Update the render-cache runtime signature to include `code_time`.
   - `code_time` becomes an input to row runtime formatting, so cached rows must invalidate when it changes.

5. Add focused tests:
   - `compute_row_runtime()` returns the segmented duration for `PLAN APPROVED` using `BEGIN -> PLAN` plus
     `CODE -> now`.
   - The result ticks for a plan-approved agent with `code_time`.
   - `patch_active_runtime_rows()` advances such a row once per second.
   - The render cache key changes when `code_time` changes.
   - Keep the existing “PLAN APPROVED parent status alone is stable” test meaningful by using a row without
     `plan_times`/`code_time`.

## Verification

Run targeted tests first:

```bash
pytest tests/ace/tui/widgets/test_agent_list_runtime_model.py \
  tests/ace/tui/widgets/test_agent_list_runtime_patching.py \
  tests/ace/tui/widgets/test_agent_render_cache.py
```

Then run the repository check as required by local instructions after code changes:

```bash
just install
just check
```

## Risks and Constraints

- The runtime must not include the approval gap between `PLAN` and `CODE`.
- Rows with `PLAN APPROVED` but missing `code_time` must remain stable and should not show a misleading runtime.
- Existing workflow-parent aggregation must continue to win when runtime children exist, because that path is more
  precise for expanded workflow rows.
- This is presentation logic in the ace TUI and should not require Rust core changes.
