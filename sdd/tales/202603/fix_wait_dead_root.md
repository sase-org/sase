---
create_time: 2026-03-28 14:20:34
status: done
prompt: sdd/prompts/202603/fix_wait_dead_root.md
---

# Plan: Fix `%wait` Resolution When Root Agent Is Dead Without `done.json`

## Problem

Agent `@l` is stuck in WAITING state for agent `@i` even though `@i` shows as DONE in the TUI. The
`sase_chop_wait_checks` chop runs every 1 second but never writes `ready.json` to unblock `@l`.

## Root Cause

There is a mismatch between how the TUI and `is_workflow_complete()` determine "done" status:

- **TUI**: Can show an agent as DONE from `workflow_state.json` (status="completed") even when `done.json` doesn't
  exist. This happens via `_workflow_loaders.py`'s `load_workflow_agents()`.
- **`is_workflow_complete()`**: Relies exclusively on `done.json` for the root agent. If the root's `done.json` is
  missing (process died between `workflow_state.json` write and `done.json` write), it returns `False`.

The `False` return **blocks the fallthrough** to `find_named_agent()` in the chop, which would otherwise resolve the
dependency via a simpler check. This creates a permanent deadlock: the chop sees the workflow as incomplete, but the
root process is dead and will never write `done.json`.

**When this happens:**

1. Root runs a plan step via `execute_workflow` → `workflow_state.json` written with status "completed"
2. Process dies (SIGKILL, OOM, crash, or error in `_finalize_loop`) before `done.json` is written to root
3. TUI shows DONE (from `workflow_state.json`), but chop disagrees (no `done.json`)

**Secondary issue:** When `root is None` in `is_workflow_complete()` (e.g., `promote_to_workflow` failed silently), the
function returns `False` instead of `None`, also blocking the fallthrough to `find_named_agent()`.

## Changes

### 1. `src/sase/agent/names.py` — Make `is_workflow_complete()` handle dead roots

Two fixes in the `is_workflow_complete` function:

**a) `root is None` → return `None` instead of `False`**

When `promote_to_workflow` fails silently, the root's `agent_meta.json` won't have `workflow_name`, so only children are
found. Without a root, we can't determine workflow completion — return `None` to let the chop fall through to
`find_named_agent()`.

**b) Dead root without `done.json` → check children instead of returning `False`**

Current behavior: root has no `done.json` → immediately return `False`.

New behavior:

- Root alive without `done.json` → `False` (still running, may write it later)
- Root dead without `done.json` → continue to check children. If all children are done or dead → `True` (workflow
  completed but root's `done.json` write failed). If any child is alive without `done.json` → `False`.

This matches the TUI's behavior: if all agents in the workflow are dead/done, the workflow is complete.

### 2. `tests/test_agent_names.py` — Update tests

- Add test: `root is None` (children exist but no root) → returns `None`
- Update existing "root dead, no done" test: when children are all done, should return `True`
- Add test: root dead, no done, child still alive → `False`
- Add test: root dead, no done, no children → `False`
