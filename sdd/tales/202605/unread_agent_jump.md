---
create_time: 2026-05-08 16:57:12
status: done
prompt: sdd/prompts/202605/unread_agent_jump.md
---
# Fix `,j` Unread Agent Jump Across Panels

## Problem

The Agents tab can render multiple tag panels at once. The unread completed-agent marker is computed from a
session-local identity set and passed to every rendered `AgentList`, so an unread completed row can be visible in any
panel. The `,j` leader action currently calls `_jump_to_next_unread_done_agent()`, which uses `_agents_visible_order()`.
That helper is explicitly scoped to the currently focused panel.

This creates a mismatch:

- the screen can visibly show an unread completed row outside the focused panel;
- the command only searches unread completed rows inside the focused panel;
- when the focused panel has none, `_jump_to_next_unread_done_agent()` returns `False`;
- leader mode reports `No unread completed agents`.

The snapshot matches this: the visible unread row is in `#chop`, while the details pane still shows an untagged agent,
so the focused panel is not the panel containing the unread row.

## Design

Make `,j` mean "next unread completed agent visible on the Agents tab", not "next unread completed agent in the current
tag panel".

The fix should:

1. Build unread completed candidates from the full visible panel layout, not only `_agents_visible_order()`.
2. Preserve the existing recency-based ordering and wrap behavior.
3. When the target is in another panel, update `_panel_group.focused_idx` before refreshing so highlight, focus, and
   details move to that panel.
4. Keep merged-panel mode and the no-panel fallback behavior equivalent to today.
5. Preserve the target unread marker, as the current method intentionally does.

Implementation should stay in the TUI layer because this is presentation/navigation state, not shared backend logic.

## Implementation Steps

1. Add a small helper in `src/sase/ace/tui/actions/agents/_core.py` that returns the current panel index for a global
   agent index by using `_panel_keys_per_agent()` and `_panel_group.panel_keys`.
2. Change `_jump_to_next_unread_done_agent()` to iterate global `_agents` indices for candidate discovery, while still
   filtering to rows that belong to rendered panels. Store each candidate's target panel index.
3. On jump, set `_panel_group.focused_idx` to the candidate panel before clearing banner focus and updating
   `current_idx`.
4. Use a full list refresh when the target panel changes or banner focus is cleared in-place; otherwise keep the
   existing single-row patch fast path.
5. Add regression tests in `tests/ace/tui/test_agent_unread_indicator.py` covering:
   - unread completed row in a non-focused tag panel is found;
   - focused panel moves to the target panel;
   - `current_idx` and unread state are preserved;
   - no unread completed rows still returns `False`.
6. Run focused tests for unread-agent behavior and keymap coverage, then run `just install` and `just check` if source
   files changed.

## Expected Outcome

Pressing `,j` should jump to `@anj.plan` in the snapshot instead of showing `No unread completed agents`, because the
command will search the full Agents tab panel layout and move focus to `#chop` when that is where the unread row lives.
