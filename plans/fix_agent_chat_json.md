---
create_time: 2026-03-28 11:38:25
status: done
---

# Fix: AGENT CHAT shows JSON metadata instead of agent reply

## Problem

When a workflow step agent completes after a plan/questions handoff (SIGTERM), the TUI "AGENT CHAT" section displays raw
JSON metadata (e.g., `{"meta_workspace": "100", "meta_project": "bug"}`) instead of the agent's actual reply text.

## Root Cause

When `sase plan` or `sase questions` runs, it SIGTERMs the agent process. This kills the process before
`workflow_executor_steps_prompt.py` can save the chat file and update the step marker's `response_path`. The execution
flow is:

1. Step marker saved with `response_path=None` (initial "running" marker)
2. LLM agent runs, produces response
3. Agent runs `sase plan` which sends SIGTERM — **process killed here**
4. Steps that never execute: save chat file, parse output, update step marker with `response_path`

After the SIGTERM, `handle_plan_marker()` (in `run_agent_exec_plan.py`) saves a replacement chat file and stores the
path in `agent_meta.json` via `update_meta_field("chat_path", ...)`. But it **never updates the step marker's
`response_path`**.

The TUI then:

1. Reads `response_path` from the step marker → `None`
2. `get_response_content()` returns `None`
3. Falls back to `format_output(agent.step_output)` → displays structured output JSON

The same issue exists in `handle_questions_marker()`.

## Fix

### Phase 1: Update step marker `response_path` after handoff chat save

In `run_agent_exec_plan.py`, after saving the chat file in both `handle_plan_marker()` and `handle_questions_marker()`,
update the step marker(s) in the artifacts directory with `response_path`.

Add a helper function (in `run_agent_helpers.py`) that globs for `prompt_step_*.json` markers in the artifacts
directory, skips embedded workflow markers (filenames containing `__`), and sets `response_path` on any marker where
it's currently unset.

Call this helper from:

- `handle_plan_marker()` after line 181 (after `update_meta_field(..., "chat_path", _planner_chat)`)
- `handle_questions_marker()` after line 399 (after `update_meta_field(..., "chat_path", _q_chat)`)

### Phase 2: Display-side guard against metadata-only fallback

In `_agent_display.py`, tighten the fallback condition so `format_output(agent.step_output)` is only used when the step
output contains displayable content (has `_raw` or `_data` key), not when it only contains `meta_*` fields or other
metadata.

This serves as a defensive measure for:

- Existing step markers from before the fix
- Any future edge cases where `response_path` fails to be set

## Files to Change

| File                                                      | Change                                                                                  |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `src/sase/axe/run_agent_helpers.py`                       | Add `update_step_marker_chat_path()` helper                                             |
| `src/sase/axe/run_agent_exec_plan.py`                     | Call helper in `handle_plan_marker()` and `handle_questions_marker()`                   |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` | Tighten fallback condition (2 places: `update_display` and `update_display_with_hints`) |
