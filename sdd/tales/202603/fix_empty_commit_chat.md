---
status: done
---

# Fix: Empty chat file in ChangeSpec COMMITS entry for `create_pull_request` flow

## Problem

When the ace-run agent runs `sase commit --method create_pull_request` (e.g. Gemini on Mercurial via retired Mercurial plugin), the
resulting ChangeSpec's COMMITS entry references a chat file that has empty Prompt and Response sections:

```
# Chat History - sase_commit
**Timestamp:** 2026-03-27 19:00:26 EDT

## Prompt

## Response
```

## Root Cause

Two-part failure:

### 1. `_create_changespec()` passes empty prompt/response

`CommitWorkflow._create_changespec()` (`src/sase/workflows/commit/workflow.py:356-368`) calls
`create_changespec_for_workflow()` with `prompt=""` and `response=""`:

```python
cs_name = create_changespec_for_workflow(
    ...
    prompt="",      # ← always empty
    response="",    # ← always empty
    ...
)
```

`create_changespec_for_workflow()` (`src/sase/workspace_provider/changespec.py:164`) then creates a new chat file with
these empty strings:

```python
chat_path = save_chat_history(prompt, response, workflow_name, timestamp=ts)
```

### 2. ace-run workflow doesn't pre-set `SASE_AGENT_CHAT_PATH`

The CRS workflow (`src/sase/workflows/crs.py:186-198`) pre-sets `SASE_AGENT_CHAT_PATH` with a predicted path before
invoking the agent, so `_append_commits_entry()` can reference the right chat file. The ace-run workflow
(`src/sase/axe/run_agent_exec.py`) does **not** pre-set this env var.

Even if it did, `create_changespec_for_workflow()` doesn't check `SASE_AGENT_CHAT_PATH` — it unconditionally creates a
new (empty) chat file.

### Why this only affects `create_pull_request`

- `create_commit` / `create_proposal`: uses `_append_commits_entry()` which reads `SASE_AGENT_CHAT_PATH`
- `create_pull_request`: uses `_create_changespec()` → `create_changespec_for_workflow()` which creates its own chat
  file

On Mercurial (retired Mercurial plugin), `create_pull_request` is the method used for new CLs, so this bug surfaces there.

## Fix

### Step 1: Pre-set `SASE_AGENT_CHAT_PATH` in ace-run workflow

**File:** `src/sase/axe/run_agent_exec.py` — in `run_execution_loop()`, before the `while True` loop.

Same pattern as CRS (`src/sase/workflows/crs.py:186-198`):

```python
from sase.history.chat import generate_chat_filename, get_chat_file_path
from pathlib import Path

chat_basename = generate_chat_filename(workflow="ace-run", timestamp=ctx.timestamp)
predicted_chat_path = get_chat_file_path(chat_basename).replace(str(Path.home()), "~")
os.environ["SASE_AGENT_CHAT_PATH"] = predicted_chat_path
```

This ensures that both `_append_commits_entry()` (for `create_commit`/`create_proposal`) and
`create_changespec_for_workflow()` (after Step 2) can reference the ace-run chat file.

### Step 2: `create_changespec_for_workflow` — prefer `SASE_AGENT_CHAT_PATH`

**File:** `src/sase/workspace_provider/changespec.py` — in `create_changespec_for_workflow()`, replace line 164.

```python
# Prefer the agent's own chat file (pre-set by ace-run or CRS) over creating
# a new one.  The file may not exist yet (it's written after the agent
# finishes), but the COMMITS entry only stores the path string.
import os
chat_path = os.environ.get("SASE_AGENT_CHAT_PATH")
if not chat_path:
    chat_path = save_chat_history(prompt, response, workflow_name, timestamp=ts)
```

This keeps backward compatibility: when `SASE_AGENT_CHAT_PATH` is not set (e.g. human CLI usage or other callers), it
falls back to creating a chat file as before.

### Step 3: Update tests

- **`tests/workspace_provider/test_changespec.py`**: Test that `create_changespec_for_workflow` uses
  `SASE_AGENT_CHAT_PATH` when set, and falls back to creating a file when not set.
- **`tests/test_commit_workflow_changespec.py`**: If it exists and covers `_create_changespec`, verify chat path
  behavior.

## Files to modify

| File                                          | Change                                                   |
| --------------------------------------------- | -------------------------------------------------------- |
| `src/sase/axe/run_agent_exec.py`              | Pre-set `SASE_AGENT_CHAT_PATH` in `run_execution_loop()` |
| `src/sase/workspace_provider/changespec.py`   | Check `SASE_AGENT_CHAT_PATH` before creating chat file   |
| `tests/workspace_provider/test_changespec.py` | Test new env var behavior                                |
