---
create_time: 2026-05-07 11:05:40
status: done
prompt: sdd/prompts/202605/plan_step_runtime_1.md
---
# Fix Plan-Step Runtime Display

## Problem

The Agents tab runtime suffix currently lets `stop_time` win over `plan_times` for completed rows. That is correct for
ordinary completed agents, but it is wrong for planner-phase rows that also carry later workflow timestamps. In the
`sase ace` snapshot, `@afk.code.r1.plan` has `BEGIN`, `PLAN`, `CODE`, and `END`, and the row displays `BEGIN -> END`
(`13m40s`). For the planner row, the runtime should be the planner phase only: `BEGIN -> PLAN`.

## Relevant Code

- `src/sase/ace/tui/models/agent_time.py` owns runtime calculation through `compute_row_runtime()`.
- `_row_runtime_terminal_time()` currently returns `stop_time` before considering `plan_times`.
- `Agent` rows may represent several related concepts:
  - ordinary leaf agents, where `stop_time` should remain the terminal runtime anchor;
  - workflow child agent steps, where non-agent steps should not render runtime suffixes;
  - planner workflow rows / follow-up planner rows, where `PLAN` is the end of the planner runtime even if `CODE` and
    `END` are also known;
  - aggregate parent rows, where `runtime_children` should continue to sum child intervals.
- Existing tests live under `tests/ace/tui/widgets/test_agent_list_runtime_model.py` and
  `test_agent_list_runtime_rendering.py`.

## Approach

1. Add focused regression coverage for the snapshot-shaped case:
   - a planner-phase row with `status="PLAN DONE"`, `start_time`, `plan_times`, `code_time`, and `stop_time` should
     render the latest relevant `PLAN` timestamp and `PLAN - BEGIN` elapsed runtime;
   - a workflow child `agent` step with `status="DONE"` and both `plan_times` and `stop_time` should likewise use `PLAN`
     when it is the planner step;
   - ordinary completed agents with both `stop_time` and incidental `plan_times` should keep the existing `stop_time`
     precedence.

2. Update `agent_time.py` to distinguish planner-phase rows from ordinary completed rows before choosing a terminal
   timestamp. The planner-phase predicate should be narrow and based on existing metadata such as
   `role_suffix == ".plan"`, `status == "PLAN DONE"`, or workflow child planner naming/role signals, so normal `DONE`
   rows do not change behavior.

3. Keep aggregate behavior intact. Parent rows with `runtime_children` should still prefer the aggregate interval; the
   child planner interval should become `BEGIN -> PLAN`, so any parent sum using that child also becomes correct.

4. Run the targeted runtime tests first, then run `just install` if needed followed by `just check` per repo memory.

## Validation

- `pytest tests/ace/tui/widgets/test_agent_list_runtime_model.py tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
- `just install`
- `just check`
