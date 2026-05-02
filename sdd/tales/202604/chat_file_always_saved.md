---
create_time: 2026-04-13 19:07:48
status: done
---

# Plan: Always save chat file so SASE_AGENT_CHAT_PATH resolves

## Problem

When an agent run is killed or plan-rejected, the predicted chat file path (set in `SASE_AGENT_CHAT_PATH` before
execution) is already stored in ChangeSpec COMMITS drawer entries (via `post_commit.py` / `commit_tracking.py`), but the
actual file is never created because `_finalize_loop` only saves the chat file when `state.loop_outcome == "completed"`.

This means: if an agent makes commits during execution and is then killed, the COMMITS entries reference
`~/.sase/chats/<name>.md` — a file that does not exist.

Additionally, `done.json` for killed/plan_rejected agents omits `response_path`, so the TUI Agents tab can't link to a
chat file for inspection either.

## Root Cause

`src/sase/axe/run_agent_exec.py` `_finalize_loop()`:

- Line 131: chat save is gated on `state.loop_outcome == "completed"`
- Line 207–225: the `else` branch (killed / plan_rejected) writes `done.json` WITHOUT `response_path` and does NOT save
  a chat file
- Line 274: `SASE_AGENT_CHAT_PATH` is set unconditionally before execution

Secondary issue: plan and questions steps in `run_agent_exec_plan.py` (lines 211, 454) call `save_chat_history` without
passing `branch_or_workspace`, causing the filename to use the shell-derived branch name instead of `ctx.cl_name` — a
potential mismatch with the predicted path.

## Fix

### Phase 1: Save chat file for all outcomes

**File: `src/sase/axe/run_agent_exec.py` — `_finalize_loop()`**

Move the chat-save call out of the `if state.loop_outcome == "completed"` block. For non-completed outcomes:

- `response_content` = empty string (no response available)
- Still save prompt + extra sections so the file exists and is useful for debugging
- Include `response_path=saved_path` in the `build_done_marker` call for the `else` branch too, so the TUI can link to
  the chat file

### Phase 2: Pass branch_or_workspace in plan/questions steps

**File: `src/sase/axe/run_agent_exec_plan.py`**

- Line ~211: add `branch_or_workspace=ctx.cl_name` to the planner `save_chat_history` call
- Line ~454: add `branch_or_workspace=ctx.cl_name` to the questions `save_chat_history` call
