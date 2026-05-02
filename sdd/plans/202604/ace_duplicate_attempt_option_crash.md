---
create_time: 2026-04-23 17:38:36
status: done
prompt: sdd/prompts/202604/ace_duplicate_attempt_option_crash.md
---
# Plan: Fix `sase ace` `DuplicateID` crash when expanding workflows with attempt history

## Goal

Fix the crash reproduced in `.sase/home/tmp/scratch/ace_error.txt` where pressing expand/layout on the Agents tab of
`sase ace` raises:

```
textual.widgets._option_list.DuplicateID:
    Unable to add Option(<text "    ↳ Attempt 1 · 14:28:10 · failed: ...">, id='attempt:20260423142806:1')
```

The crash kills the TUI any time a workflow with a prior attempt (retry) is expanded far enough to reveal two or more
child steps.

## Root cause

Crash path (from the traceback):

`action_expand_or_layout` → `_expand_fold` → `_refilter_agents` → `_finalize_agent_list` →
`_refresh_agents_display(list_changed=True)` → `AgentList.update_list` (`src/sase/ace/tui/widgets/agent_list.py`).

In `update_list` (around lines 196–248), for every agent in the list, we:

1. Emit an option for the agent itself, id = `f"{index}:{agent.agent_type.value}:{agent.cl_name}"`.
2. Emit one option per `record` in `agent.attempt_history`, via `_format_attempt_option` (line 497), where
   `option_id = f"attempt:{agent.raw_suffix}:{record.attempt_number}"` (line 519).

The problem is that **workflow child steps share the parent workflow's `raw_suffix`**.
`_loading_helpers.load_agents_from_disk` (lines 137–140) unconditionally runs:

```python
for agent in all_agents:
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir:
        agent.attempt_history = load_attempt_history(artifacts_dir)
```

`get_artifacts_dir` for a workflow child returns the same directory as its parent workflow (they point at the same
`ace-run/<timestamp>` dir), so child steps inherit the parent's full `attempt_history` list.

The error-file trace confirms this with concrete values:

- Parent workflow: `cl_name='pat_fix_far_past_1'`, `raw_suffix='20260423142806'`,
  `attempt_history=[AttemptRecord(attempt_number=1, ...)]`.
- Child step `main`: `cl_name='main'`, `parent_timestamp='20260423142806'`, `raw_suffix='20260423142806'`, identical
  `attempt_history`.
- Child step `diff`: same `raw_suffix='20260423142806'`, identical `attempt_history`.

When the workflow is expanded, the parent emits id `attempt:20260423142806:1`, then the first child tries to emit the
same id → `DuplicateID` → crash.

Conceptually, attempts belong to the workflow as a whole, not to each child step. Emitting attempt rows under each child
is not just buggy — it's semantically wrong (we'd show the same "Attempt 1" three times).

## Design

Minimal, semantic fix at the display layer: skip the attempt-child emission loop for any agent that is a workflow child.

In `AgentList.update_list` (`src/sase/ace/tui/widgets/agent_list.py`, lines ~229–248), wrap the existing block

```python
for record in agent.attempt_history:
    is_selected_attempt = (...)
    attempt_option = self._format_attempt_option(...)
    self.add_option(attempt_option)
    ...
```

with:

```python
if not agent.is_workflow_child:
    for record in agent.attempt_history:
        ...
```

`Agent.is_workflow_child` (agent.py:510) is already defined as
`self.parent_workflow is not None or self.parent_timestamp is not None` — exactly the condition we want.

This keeps attempts attached to the single workflow-parent row (and to plain non-workflow agents), which is both correct
UX and eliminates the duplicate-ID class of crashes.

## Design decisions

1. **Display-layer fix, not loader-layer.** We could stop populating `attempt_history` on workflow-child agents in
   `_loading_helpers.load_agents_from_disk`. Grep shows `attempt_history` is read by several other modules
   (`_agent_display.py`, `_agent_display_parts.py`, `keybinding_footer.py`, `_panels.py`, `agent_bundle.py`). Stripping
   it at load time risks silently breaking any of those readers that look at a child's `attempt_history` for UI state.
   Fixing only the row-emission is the narrowest change that resolves the crash without altering the data model.

2. **Not a dedup-at-add-time band-aid.** Suppressing duplicates inside `add_option` would paper over the root bug and
   add dead code. The "attempts belong to the workflow" framing is simpler and matches user expectations.

3. **No change to `_format_attempt_option` or the option ID scheme.** The ID `attempt:<raw_suffix>:<n>` is already
   unique _per workflow_; with the emission guard in place, it's emitted at most once.

## Changes

### 1. `src/sase/ace/tui/widgets/agent_list.py`

In `AgentList.update_list`, guard the `for record in agent.attempt_history:` block (~line 232) with
`if not agent.is_workflow_child:`. No other logic changes.

### 2. `tests/ace/tui/widgets/test_agent_list_attempts.py`

Add a regression test that reproduces the crash scenario:

- Build a workflow parent agent (`agent_type=WORKFLOW`, `raw_suffix='20260423142806'`, `appears_as_agent=True`) carrying
  one `AttemptRecord`.
- Build a workflow child (`parent_workflow='w'`, `parent_timestamp='20260423142806'`, `raw_suffix='20260423142806'`)
  carrying the **same** `attempt_history` list.
- Call `AgentList().update_list([parent, child], current_idx=0)`.
- Assert no exception is raised and `_row_entries` is `[(0, None), (0, 1), (1, None)]` — i.e. exactly one attempt row,
  attributed to the parent, and the child contributes only its own row.

Existing tests in `test_agent_list_attempts.py` exercise non-workflow agents and should continue to pass unchanged.

## Verification

- `just check` (ruff + mypy + pytest with coverage).
- Manually: run `sase ace` against a project that has a retried workflow, navigate to the Agents tab, and expand the
  workflow; confirm the list renders and the "Attempt 1" row appears once under the workflow parent rather than under
  every child.
- Grep for other callers of `_format_attempt_option` to confirm the change doesn't regress them (expected: only
  `AgentList.update_list` calls it).
