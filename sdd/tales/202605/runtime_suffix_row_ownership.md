---
create_time: 2026-05-06 12:48:21
status: done
prompt: sdd/prompts/202605/runtime_suffix_row_ownership.md
---
# Plan: Runtime Suffix Row Ownership Correction

## Context

The previous runtime suffix fix split true workflow prompt-step rows from linked follow-up rows, but it added one
incorrect ownership rule: if a prompt-step row belongs to an `appears_as_agent` parent workflow, suppress the
prompt-step runtime. That made rows such as `1/1.plan` lose their own static runtime even though the underlying plan
agent is `DONE` and has `run_started_at` / `stopped_at` metadata.

The intended display has three separate runtime owners:

- The main parent row, such as `LEGEND APPROVED`, owns the aggregate workflow runtime. Its current behavior is correct
  and should keep ticking while an approved follow-up is active.
- The prompt-step agent row, such as `1/1.plan`, owns the runtime of that specific prompt-step agent. If it is `DONE`,
  it should show a stable finish timestamp and elapsed duration.
- The linked follow-up row, such as `1/1.legend`, owns the runtime of that specific follow-up agent/workflow. If it is
  running, it should tick from its own `run_start_time` or `start_time`, not from the parent plan's timestamp.

The current code violates the second point in `src/sase/ace/tui/models/agent_time.py`:

```python
if agent.parent_workflow is None:
    return True
if agent.step_type != "agent":
    return False
return not agent.parent_appears_as_agent
```

That last line should not be a runtime-eligibility rule. `parent_appears_as_agent` describes presentation context, not
runtime ownership.

## Design

1. Restore row-local runtime eligibility for prompt-step agent rows.
   - Keep `parent_workflow is None` eligible so top-level rows and linked follow-up rows remain visible.
   - For true workflow prompt-step rows (`parent_workflow is not None`), show runtimes only for `step_type == "agent"`.
   - Do not suppress `step_type == "agent"` rows based on `parent_appears_as_agent`.

2. Preserve aggregate parent behavior.
   - Do not change `_ACTIVE_PARENT_STATUSES` or the `runtime_suffix_ticks()` recursion through `followup_agents`.
   - A parent in `LEGEND APPROVED` should continue to tick using the parent row's own start/run-start data while the
     workflow/follow-up chain is active.

3. Preserve follow-up ownership.
   - A linked follow-up row is identified by `parent_timestamp` with `parent_workflow is None`.
   - It should continue to use its own `start_time`, `run_start_time`, and `stop_time` in `compute_row_runtime()`.
   - Running linked follow-up rows should continue to return `True` from `runtime_suffix_ticks()`.

4. Keep non-agent workflow steps hidden from runtime suffixes.
   - `bash`, `python`, `parallel`, embedded pre-prompt, and other non-agent prompt-step rows should still return
     `(None, None)` and should not participate in one-second runtime patching.

5. Clean up the now-misleading test/field usage narrowly.
   - Update tests that currently assert an `appears_as_agent` prompt-step has no runtime; they should assert the inverse
     for `step_type == "agent"` and terminal/static behavior for `DONE`.
   - If `parent_appears_as_agent` has no remaining visible/render-cache purpose after the eligibility change, remove it
     from the runtime cache key and consider removing the field/loader enrichment that was added solely for the previous
     suppression rule. If other code uses it, leave the field but keep it out of runtime eligibility.

## Test Plan

Update `tests/ace/tui/widgets/test_agent_list_runtime.py` with focused cases:

- `compute_row_runtime()` returns a finish timestamp and elapsed duration for a `DONE` prompt-step agent under an
  `appears_as_agent` parent, modeling `1/1.plan`.
- `runtime_suffix_ticks()` returns `False` for that terminal `DONE` prompt-step row, proving the suffix is static.
- `format_agent_option()` renders the static suffix for the same row.
- A running linked follow-up workflow with only `parent_timestamp` set still returns/ticks its own elapsed runtime,
  modeling `1/1.legend`.
- The parent row in `LEGEND APPROVED` still ticks, preserving the aggregate workflow runtime.
- Existing non-agent workflow child tests for `bash` and `python` continue to assert no suffix.

Run focused verification first:

```bash
.venv/bin/python -m pytest tests/ace/tui/widgets/test_agent_list_runtime.py
```

Then run the repo gate after code changes:

```bash
just install
just check
```
