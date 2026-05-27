---
create_time: 2026-05-26 20:18:07
status: done
prompt: sdd/prompts/202605/apostrophe_jump_marks_agent_read.md
---
# Fix Apostrophe Agent Jump Read Acknowledgement

## Context

On the Agents tab, completed-agent unread state is stored in `_unread_completed_agent_ids` and rendered as a
checkbox-style unread marker. Rows are acknowledged through `_acknowledge_agent_unread()`, which also dismisses matching
completion notifications and patches the affected row when possible.

The normal Agents-tab navigation paths already call the read/unread helpers:

- j/k navigation in `src/sase/ace/tui/actions/navigation/_basic.py` arms a manually-unread row when leaving it and
  acknowledges the target agent row.
- Mouse/list selection in `src/sase/ace/tui/actions/_event_widgets.py` does the same when the selected row changes.
- Sibling/panel jumps in `src/sase/ace/tui/actions/agents/_siblings.py` and `_panel_navigation.py` follow the same
  pattern.

The apostrophe entry-jump dispatcher in `src/sase/ace/tui/actions/navigation/_entry_jump_dispatch.py` currently handles
Agents-tab agent targets by updating panel focus, clearing banner focus, and assigning `current_idx`, then exits jump
mode. Because it bypasses `_acknowledge_agent_unread()`, landing on an unread completed agent leaves its unread marker
visible.

## Plan

1. Add the missing Agents-tab selection side effects to entry-jump dispatch.

   In the agent-target branch of `_handle_entry_jump_key()`, preserve the current history behavior, then:
   - Identify the old selected agent when focus is currently on an agent row.
   - If the jump leaves that old agent, call `_arm_manual_unread_after_departure()` so manual unread behaves like j/k
     and mouse navigation.
   - After setting `current_idx` and clearing banner focus for the target row, call `_acknowledge_agent_unread()` for
     the target agent when available.

2. Keep banner jumps unchanged except for manual-unread departure parity.

   Jumping to a collapsed banner should not acknowledge any target agent, because no agent row is selected. If the user
   leaves an agent row to focus a banner, the old manual-unread guard should be armed the same way it is for j/k.

3. Add focused regression tests.

   Extend the existing Agents-tab jump harness in `tests/ace/tui/test_jump_hints_for_folded_banners.py` or add a small
   dedicated test file to cover:
   - Apostrophe hint jump to an unread DONE agent clears `_unread_completed_agent_ids`.
   - The matching row patch path is exercised when the target can be patched.
   - Manual-unread target rows remain unread while guarded.
   - Jumping away from a manually-unread current row arms the manual guard, so a later return can acknowledge it.
   - Banner-target jumps still do not acknowledge an agent row.

4. Run targeted tests first, then the repo check.

   Execute the relevant TUI tests for entry-jump and unread navigation. Because this repo’s memory says `just check` is
   required after code changes, run `just install` if needed and then `just check` before finishing.

## Risks

- `_acknowledge_agent_unread()` may patch or refresh rows while `_exit_entry_jump_mode()` also refreshes the Agents
  display. This is already acceptable functionally, but the implementation should avoid depending on duplicate refresh
  ordering.
- Manual-unread semantics are subtle: the explicit manual guard should prevent immediate clearing, but navigating away
  should arm the row for later normal acknowledgement, matching existing j/k and mouse behavior.
