---
create_time: 2026-03-29 15:20:10
status: done
prompt: sdd/prompts/202603/fix_spec_feedback.md
---

# Fix: Spec File Missing Feedback (Additional Requirements)

## Problem

When a user provides feedback during plan approval (adding "Additional Requirements"), the feedback is correctly
accumulated in `state.current_prompt` and used to spawn a replanning agent. However, when the revised plan is finally
approved and the SDD spec file is committed, the spec is written using `state.original_prompt` — which does NOT contain
the feedback. This means the committed spec file is missing the "### Additional Requirements" section.

## Root Cause

In `src/sase/axe/run_agent_exec_plan.py`, line 261:

```python
expanded = expand_prompt_for_spec(state.original_prompt)
```

This should use `state.current_prompt` instead, which includes the accumulated feedback bullets appended as "###
Additional Requirements". Both fields start as the same value (line 266-271 of `run_agent_exec.py`), so when there is no
feedback the behavior is identical. But after feedback rounds, only `current_prompt` has the full content.

The same issue exists in the fallback on line 266:

```python
expanded = state.original_prompt
```

## Fix

Two lines in `handle_plan_marker()` need to change from `state.original_prompt` to `state.current_prompt`:

1. **Line 261**: `expand_prompt_for_spec(state.original_prompt)` → `expand_prompt_for_spec(state.current_prompt)`
2. **Line 266**: `expanded = state.original_prompt` → `expanded = state.current_prompt`

## Also Fix: The Already-Committed Spec File

The existing `specs/202603/branch_naming_reform.md` file needs to be updated to include the missing section:

```markdown
### Additional Requirements

- Make sure you make this work with the ../retired Mercurial plugin repo, but do NOT change any of the behavior for that VCS
  provider. It's fine if you need to make code changes to that repo, but none of the behavior should change.
```

This should be appended before the `sase ace` Snapshot section (i.e., right after the closing of the main prompt text,
before the snapshot).

## Verification

- Run `just check` to ensure lint/type/test pass after the code change.
