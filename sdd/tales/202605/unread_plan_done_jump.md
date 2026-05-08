---
create_time: 2026-05-08 17:09:50
status: done
prompt: sdd/prompts/202605/unread_plan_done_jump.md
---
# Fix unread-agent jump for PLAN DONE terminal statuses

## Problem

The previous unread jump fix correctly made `,j` search all rendered agent panels, but it still uses a narrower
definition of "completed" than the rest of the Agents tab.

The unread finalizer in `src/sase/ace/tui/actions/agents/_loading_finalize.py` marks newly terminal rows unread when
their status enters `DISMISSABLE_STATUSES`. That set includes:

- `DONE`
- `FAILED`
- `PLAN COMMITTED`
- `PLAN DONE`
- `PLAN REJECTED`
- `EPIC CREATED`

The jump and footer availability paths still hard-code only `("DONE", "FAILED")`:

- `AgentsMixinCore._has_unread_completed_agent()`
- `AgentsMixinCore._jump_to_next_unread_done_agent()`
- command-context completed/unread counts in `src/sase/ace/tui/commands/context.py`

That creates the observed behavior: a `PLAN DONE` row can be placed in `_unread_completed_agent_ids`, and the row
renderer can show its unread marker, but the `,j` action does not consider it a candidate and the footer/palette state
can say there are no unread completed agents.

## Design

Use one shared status predicate for the unread-completed navigation surface: an unread completed agent is a visible row
whose status is in `DISMISSABLE_STATUSES` and whose identity is in `_unread_completed_agent_ids`.

This keeps the jump semantics aligned with the finalizer that creates unread entries. It also handles adjacent terminal
plan states (`PLAN COMMITTED`, `PLAN REJECTED`, `EPIC CREATED`) without adding another one-off status list. The change
is still presentation-layer TUI behavior, so it belongs in this repo rather than the Rust core.

I will avoid broad unrelated cleanup of every `("DONE", "FAILED")` predicate in the TUI. Some of those gates mean
different things, such as edit-chat/resume affordances or diff-path assumptions. This fix should touch only the unread
completed indicator/jump/count paths and their tests.

## Implementation Steps

1. Add a tiny local predicate in `src/sase/ace/tui/actions/agents/_core.py`, for example
   `_is_unread_completed_status(status: str) -> bool`, backed by `DISMISSABLE_STATUSES`.
2. Use that predicate in:
   - `_has_unread_completed_agent()`
   - `_jump_to_next_unread_done_agent()` candidate filtering
3. Update `src/sase/ace/tui/commands/context.py` so command-palette/footer context counts use the same terminal set for:
   - `_completed_agent_count()`
   - `_unread_completed_agent_count()` This keeps command availability for "Jump to next unread completed agent"
     consistent with the leader action.
4. Add regression coverage in `tests/ace/tui/test_agent_unread_indicator.py`:
   - finalizer marks a `RUNNING -> PLAN DONE` transition unread
   - `_has_unread_completed_agent()` returns true for unread `PLAN DONE`
   - `,j` jumps to an unread `PLAN DONE` row, preserving unread state and existing recency behavior
   - the existing cross-panel test uses `PLAN DONE` or add a sibling cross-panel test so the prior panel fix is verified
     with the status that failed in practice
5. Add or update command-context tests in `tests/test_command_palette_wiring.py` so completed and unread-completed
   counts include `PLAN DONE` while still excluding active statuses such as `RUNNING` / `PLANNING`.
6. Run focused verification:
   - `.venv/bin/pytest tests/ace/tui/test_agent_unread_indicator.py`
   - `.venv/bin/pytest tests/test_command_palette_wiring.py`
   - `.venv/bin/pytest tests/ace/tui/test_show_agent_run_log_keymap.py`
7. Because this workspace can have stale dependencies, run `just install` first if the focused tests cannot import local
   dev dependencies.
8. Run `just check` before reporting completion, since source files will change.

## Expected Outcome

`PLAN DONE` agents that become unread will behave like other completed unread agents:

- the unread footer/keybinding affordance appears;
- the command palette sees the jump command as available;
- `,j` jumps to the newest visible unread terminal row, including across tag panels;
- the jump still preserves the target unread marker until normal selection acknowledgement clears it.
