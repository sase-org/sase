---
create_time: 2026-03-27 15:36:19
status: done
prompt: sdd/prompts/202603/wait_workflow_completion.md
---

# Plan: Make `%wait:a` Work With Multi-Agent Workflows

## Problem

When agent `a` proposes a plan, `promote_to_workflow()` renames it to `a.1` (planner) and creates `a.2` (coder). The
`%wait:a` dependency check in `sase_chop_wait_checks.py` calls `find_named_agent("a")` which returns a **single** agent.
We need it to check that **ALL** agents in the workflow have completed.

## Key Observations

- `done.json` is only written to the ROOT and LAST step's artifacts dirs (not intermediate feedback rounds)
- All agents in a workflow share the same PID (same process loop)
- All workflow agents have `workflow_name` set to the base name (e.g., `"a"`)
- Follow-up agents have `parent_timestamp` pointing to the root

## Changes

### 1. `src/sase/agent/names.py` — Add `is_workflow_complete()`

Add a function that checks whether ALL agents in a multi-agent workflow are done.

```python
def is_workflow_complete(name: str) -> bool | None:
```

**Returns:**

- `True` — root has `done.json` AND no child is still alive without `done.json`
- `False` — workflow exists but isn't fully complete
- `None` — no agents with `workflow_name == name` found (not a workflow)

**Logic:**

1. Scan `~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json` for `workflow_name == name`
2. If none found → return `None`
3. Find the root agent (no `parent_timestamp`)
4. If root has no `done.json`:
   - If root process alive → `False` (still running)
   - If root process dead → `False` (crashed without completion marker)
5. Root has `done.json` → check all children:
   - If any child is alive AND lacks `done.json` → `False`
6. All children done or dead → `True`

Step 5 handles intermediate agents (feedback rounds) that never receive `done.json` — they share the root's PID, so once
the root is done and the process exits, they appear dead.

### 2. `src/sase/scripts/sase_chop_wait_checks.py` — Use workflow-aware checking

Replace the single-agent check with a workflow-first check:

```python
from sase.agent.names import find_named_agent, is_workflow_complete

all_done = True
for name in waiting_for:
    workflow_status = is_workflow_complete(name)
    if workflow_status is not None:
        if not workflow_status:
            all_done = False
            break
    else:
        agent = find_named_agent(name)
        if agent is None or not agent.is_done:
            all_done = False
            break
```

When `is_workflow_complete` returns `None` (not a workflow), we fall back to the existing `find_named_agent` behavior.
This handles:

- Simple agents (no plan proposed)
- Agents before `promote_to_workflow` is called (still have `name="a"`, no `workflow_name`)

### 3. `tests/test_agent_names.py` — Add `TestIsWorkflowComplete`

Test cases using the existing `_make_agent` helper:

| Test                          | Setup                                            | Expected |
| ----------------------------- | ------------------------------------------------ | -------- |
| No workflow agents            | No agents with `workflow_name`                   | `None`   |
| Root alive, no done           | Root alive, no `done.json`                       | `False`  |
| Root done, all children done  | Root + coder both have `done.json`               | `True`   |
| Root done, child alive        | Root done, coder alive no `done.json`            | `False`  |
| Root done, child dead no done | Root done, intermediate dead no `done.json`      | `True`   |
| Root dead, no done            | Root dead, no `done.json`                        | `False`  |
| Single root with done         | Promoted root (no children yet), has `done.json` | `True`   |
