---
create_time: 2026-05-06 13:18:21
status: done
prompt: sdd/prompts/202605/plan_step_runtime.md
---
# Plan: Fix completed plan-step runtime suffixes

## Problem

In the Agents tab, the selected workflow child step in the `sase ace` snapshot is `DONE` and shows:

- `BEGIN | 2026-05-06 13:10:07`
- `PLAN  | 2026-05-06 13:14:53`

The row runtime currently shows about `5m20s`, which corresponds to elapsed time from `BEGIN` to the current refresh
time or another later marker. For a completed plan-producing step, the runtime suffix should represent the planner
drafting interval: `PLAN - BEGIN`, which is `4m46s` for the snapshot.

## Current Shape

- Runtime suffix rendering flows through `src/sase/ace/tui/widgets/_agent_list_render_layout.py`.
- Actual duration selection lives in `src/sase/ace/tui/models/agent_time.py::compute_row_runtime`.
- `Agent` already carries the needed timestamps:
  - `start_time`: initial spawn or wait timestamp.
  - `run_start_time`: actual `BEGIN` timestamp after waiting.
  - `stop_time`: explicit `END` timestamp when available.
  - `plan_times`: one or more `PLAN` submission timestamps.
- The metadata panel in `Agent.timestamps_display` already renders `PLAN` from `plan_times`, so this is a
  display-duration selection bug, not a missing artifact parsing issue.

## Proposed Change

1. Add a small helper in `agent_time.py` that chooses the elapsed end timestamp for row runtime display.
   - Use `stop_time` first when present, preserving existing behavior for ordinary terminal agents with an `END`.
   - For completed plan-producing rows with `plan_times` and no `stop_time`, use the latest `PLAN` timestamp as the
     effective end.
   - Keep active rows unchanged: use `now` for running statuses and pure waiting rows still render no suffix.

2. Update `compute_row_runtime` to use that helper.
   - The elapsed start remains `run_start_time or start_time`, preserving the existing rule that waiting time does not
     inflate runtime.
   - For `DONE`/`PLAN DONE` rows with an effective terminal milestone, return the milestone timestamp plus
     `milestone - BEGIN` elapsed.
   - If a done row still has neither `stop_time` nor `plan_times`, preserve the existing fallback rather than hiding the
     suffix.

3. Add focused tests in `tests/ace/tui/widgets/test_agent_list_runtime.py`.
   - Regression: a `DONE` workflow child `agent` step with `run_start_time=13:10:07`, `plan_times=[13:14:53]`, and no
     `stop_time` renders `13:14:53 · 4m46s`.
   - Guardrail: when both `stop_time` and `plan_times` exist, `stop_time` still wins for normal completed rows.
   - If needed, add one direct `compute_row_runtime` assertion and one rendered suffix assertion so both the model
     helper and UI string are covered.

## Validation

- Run the focused runtime test file:
  - `just test tests/ace/tui/widgets/test_agent_list_runtime.py`
- Because this repo requires it after changes, run:
  - `just install`
  - `just check`

## Risks

- The main risk is over-applying `PLAN` timestamps to parent plan workflows where the row intentionally represents a
  broader lifecycle. Keeping `stop_time` precedence and limiting the new fallback to rows without `stop_time` avoids
  changing completed rows that already have an explicit `END`.
- Multiple `PLAN` timestamps can exist after feedback. Using the latest plan timestamp matches the visible metadata
  model and the final submitted plan for that row.
