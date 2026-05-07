---
create_time: 2026-05-06 19:57:59
status: done
prompt: sdd/prompts/202605/agent_runtime_aggregation.md
---
# Plan: Aggregate Parent Agent Runtime From Child Agent Work

## Problem

The Agents tab currently computes the right-side runtime suffix for a parent agent/workflow mostly from the parent's own
begin timestamp. That makes a plan/workflow parent continue accumulating wall-clock time while the process is paused for
user input, such as plan approval, questions, or HITL. In the reported snapshot, the parent row shows `6m27s` while the
child rows show `2m56s` and `3m05s`; the parent should instead show the sum of the child agent work, approximately
`6m01s`, and it should not tick while waiting for the user to approve the plan.

## Intended Semantics

1. Keep runtime suffix behavior unchanged for ordinary leaf agents.
2. For a workflow/plan parent with visible child agent work, display aggregate productive runtime: the sum of the child
   agent row runtimes.
3. Count only agent work intervals, not wall-clock idle intervals while waiting for dependencies, plan approval,
   questions, or HITL.
4. Use each child's existing runtime semantics:
   - `run_start_time` wins over `start_time` so dependency waits are excluded.
   - `stop_time` ends completed/failed runs.
   - for a completed planner step without `stop_time`, `plan_times` ends the planner interval at plan submission.
   - active running/retrying child work ends at `now`.
   - pre-run `WAITING` with no `run_start_time` contributes zero.
5. A parent row should tick only when at least one contributing child interval is active. `PLANNING`, `QUESTION`, and
   `WAITING INPUT` parent rows should not tick merely because they are awaiting user feedback.
6. The terminal timestamp shown for an aggregate parent should be the latest contributing child terminal timestamp.
   Active aggregate parents keep the current active-row style with no finish timestamp.

## Technical Design

### 1. Add an explicit runtime-child relationship on `Agent`

Add a non-serialized dataclass field such as:

```python
runtime_children: list["Agent"] = field(default_factory=list)
```

This should be separate from `followup_agents`, because parent runtime must include both:

- direct workflow prompt-step children from `workflow_agent_steps`
- plan-chain follow-up agents such as `.2`, `.q`, `.code`, `.epic`, `.commit`

`followup_agents` is already used by detail/status logic, so keeping a dedicated runtime list avoids broadening that
field's meaning.

### 2. Populate runtime children during the existing relationship pass

Populate the new field where the loader already has the complete relationship context:

- In `src/sase/ace/tui/models/_agent_status_overrides.py`, keep the existing `followup_agents` attachment for follow-up
  metadata/status behavior.
- In `src/sase/ace/tui/models/_agent_ordering.py`, after building `steps_by_parent` and `followups_by_parent`, attach
  runtime children to each parent by raw suffix:
  - include direct workflow step children whose `step_type == "agent"`
  - include direct follow-up agents under that parent
  - preserve the same natural display order used for insertion
  - clear/rebuild `runtime_children` each load so refreshes are idempotent

This keeps the relationship local to the TUI model layer and avoids changing artifact formats or Rust scanning. The Rust
core currently provides raw scanned metadata; the aggregate calculation is still presentation-model behavior unless we
later need the same aggregate in non-TUI clients.

### 3. Refactor runtime calculation into reusable interval helpers

In `src/sase/ace/tui/models/agent_time.py`, introduce private helpers that return structured runtime data instead of
only formatted strings, for example:

- `_leaf_runtime_interval(agent, now) -> RuntimeInterval | None`
- `_aggregate_runtime(agent, now) -> RuntimeInterval | None`

The interval data should include:

- elapsed seconds
- latest terminal timestamp, if all contributing work is terminal
- active/ticking boolean

`compute_row_runtime()` can then format either the leaf interval or aggregate interval with `format_compact_duration()`
and `_format_finish_timestamp()`.

For aggregate parents:

- if `agent.runtime_children` is non-empty, sum child elapsed seconds recursively using the same helper
- if any child interval is active, the aggregate is active
- if no child interval contributes, fall back to the leaf behavior

### 4. Pause user-waiting parent states

Adjust the fallback leaf behavior so user-waiting statuses do not grow from `start_time` to `now`:

- `PLANNING` with `plan_times` should end at the latest plan submission time
- `QUESTION` with `questions_times` should end at the latest question submission time
- `WAITING INPUT` should not tick solely because the workflow is blocked; if it has no contributing child work, render
  no growing runtime or a stable interval only when a reliable terminal marker exists

This catches plan-only parents and HITL/question pauses even when no explicit runtime child list is available.

### 5. Update ticking decisions

Change `runtime_suffix_ticks()` so it follows the same aggregate semantics:

- aggregate parent ticks if any runtime child contributes an active interval
- leaf agent ticks under the current running/retrying/waiting-after-run rules
- parent status alone, such as `PLAN APPROVED`, should not make the row tick from parent begin time

This prevents `patch_active_runtime_rows()` from patching paused rows and keeps live updates aligned with the formatted
runtime.

### 6. Tests

Add focused tests in the existing runtime test suite:

- `tests/ace/tui/widgets/test_agent_list_runtime_model.py`
  - aggregate parent runtime equals completed planner step plus active coder child, not wall-clock parent age
  - `PLANNING` parent with only a completed planner child is stable and does not tick
  - `PLAN APPROVED` parent ticks because the coder child ticks, and elapsed is child-sum based
  - `QUESTION` or `WAITING INPUT` parent does not tick without active child work
  - pre-run `WAITING` child contributes zero
- `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
  - rendered suffix for the snapshot-like case shows child-sum duration
- `tests/ace/tui/widgets/test_agent_list_runtime_patching.py`
  - active aggregate parent patches only while a runtime child is active
  - paused planning/question rows are skipped
- loader/order tests around `_sort_and_reorder()` or a small direct unit test to verify `runtime_children` is populated
  with workflow agent steps plus follow-ups and does not duplicate across repeated calls

### 7. Verification

Run targeted tests first:

```bash
python -m pytest tests/ace/tui/widgets/test_agent_list_runtime_model.py \
  tests/ace/tui/widgets/test_agent_list_runtime_rendering.py \
  tests/ace/tui/widgets/test_agent_list_runtime_patching.py
python -m pytest tests/test_agent_loader_status_overrides.py tests/test_agent_loader.py
```

Because this repo requires full verification after code changes, run:

```bash
just install
just check
```

## Risks And Constraints

- Avoid double-counting follow-up workflow wrappers and their internal prompt step children. The first implementation
  should count direct visible child agent rows under the parent, matching the current Agents tab display.
- Keep artifact schema unchanged unless inspection during implementation shows missing timestamps that cannot be derived
  from existing metadata.
- Do not move this into Rust unless a second client needs the same aggregate value outside the TUI model layer.
