---
create_time: 2026-04-11 17:15:28
status: done
prompt: sdd/prompts/202604/fix_chat_filename_prefix.md
---

# Plan: Fix chat filename using wrong prefix (branch name instead of CL name)

## Problem

The `sase ace` snapshot shows a COMMITS entry for ChangeSpec `bs_allow_entity_1` referencing:

```
CHAT: ~/.sase/chats/bs_allow_schema-ace_run-260411_163347.md (17m39s)
```

This file doesn't exist on the machine.

## Root Cause

In `run_agent_exec.py`, both the **predicted** chat path (line 262) and the **actual** chat save (line 138) call
`generate_chat_filename` / `save_chat_history` **without** passing `branch_or_workspace`. This causes them to fall
through to `_get_branch_or_workspace_name()`, a shell command that returns the current VCS branch name — a value that
can **change** during the ace-run.

Here's what happens:

1. The ace-run starts. The workspace branch is `bs_allow_schema` (the root ancestor CL).
2. `run_execution_loop` computes the predicted path: `bs_allow_schema-ace_run-260411_163347.md`, stores it in
   `SASE_AGENT_CHAT_PATH`.
3. The agent makes commit (2). The `sase commit` workflow reads `SASE_AGENT_CHAT_PATH` and writes the CHAT drawer entry
   with the predicted path.
4. During the agent's work, the branch changes (e.g., the VCS switches to `bs_allow_entity_1`).
5. `_finalize_loop` calls `save_chat_history`, which again calls `_get_branch_or_workspace_name()` — but now it returns
   the **new** branch name.
6. The actual file is saved with a different prefix (e.g., `bs_allow_entity_1-ace_run-...`).
7. The COMMITS entry still points to `bs_allow_schema-ace_run-...`, which doesn't exist.

The stable, correct identifier to use is `ctx.cl_name` — the ChangeSpec name that the ace-run is targeting. It doesn't
change during the run and directly identifies what the chat belongs to.

## Changes

### 1. `src/sase/axe/run_agent_exec.py` — Pass `ctx.cl_name` as `branch_or_workspace`

**Prediction (line 262):**

```python
# Before
chat_basename = generate_chat_filename(workflow="ace-run", timestamp=ctx.timestamp)

# After
chat_basename = generate_chat_filename(
    workflow="ace-run", branch_or_workspace=ctx.cl_name, timestamp=ctx.timestamp
)
```

**Actual save (line 138):**

```python
# Before
saved_path = save_chat_history(
    prompt=state.current_prompt,
    response=response_content,
    workflow="ace-run",
    timestamp=ctx.timestamp,
    extra_sections=extra,
)

# After
saved_path = save_chat_history(
    prompt=state.current_prompt,
    response=response_content,
    workflow="ace-run",
    timestamp=ctx.timestamp,
    extra_sections=extra,
    branch_or_workspace=ctx.cl_name,
)
```

### 2. `src/sase/workflows/crs.py` — Same fix for CRS workflow

CRS has the same pattern at line 192 (missing `branch_or_workspace`). The CRS class should have access to the CL name
and pass it through. Need to check what attribute holds the CL name in the CRS context and pass it.

### 3. Tests — Update existing tests or add new ones

Verify that any existing tests for `generate_chat_filename` or `save_chat_history` in the ace-run context account for
the `branch_or_workspace` parameter.
