---
create_time: 2026-05-24 13:32:27
status: done
---
# Plan: Preserve Leader Notification Footer During Agents Refresh

## Context

The ACE TUI footer is intentionally conditional: it only shows keymaps whose availability depends on selected rows or
transient app state. In leader mode on the Agents tab, the `n` keymap (`jump_to_notification`) should appear when the
currently selected agent is in a notification-backed status such as `PLAN` or `QUESTION`.

The reported failure is that auto-refresh can repaint the LEADER footer and remove the `n` keymap even while a
`PLAN`/`QUESTION` agent such as `a98` remains selected.

## Root Cause

There are two paths that repaint the leader footer on the Agents tab:

1. `LeaderModeMixin._update_leader_footer(...)`, used when leader mode starts, computes `has_notification` from the
   selected agent status and passes it to `KeybindingFooter.update_leader_bindings(...)`.
2. `DetailMixin._apply_agent_footer_update(...)`, used by Agents-tab display refreshes including auto-refresh/detail
   refreshes, detects active leader mode and calls `update_leader_bindings(...)` but does not pass `has_notification`.

Because `KeybindingFooter.update_leader_bindings(...)` defaults `has_notification=False`, the second path can overwrite
a correct leader footer with one missing `n`.

## Implementation

Update `src/sase/ace/tui/actions/agents/_display_detail.py` so the active leader mode branch derives the selected
agent's notification availability from `current_agent` and passes `has_notification` alongside the existing unread and
stopped flags.

Keep the scope presentation-only. This does not need Rust core changes because the bug is caused by a footer repaint
losing already-known selected-agent state.

## Tests

Add focused regression coverage that exercises `DetailMixin._apply_agent_footer_update(...)` while leader mode is
active:

- selected agent status `PLAN` preserves/passes `has_notification=True`;
- a non-notification status passes `has_notification=False`;
- existing unread/stopped flags continue to flow through the same refresh path.

Also keep direct footer behavior covered by existing `KeybindingFooter` tests.

## Verification

Run the focused tests first:

```bash
pytest tests/ace/tui/test_agent_display_defer_detail.py tests/ace/tui/test_show_agent_run_log_keymap.py
```

Because repo instructions require it after source/test changes, run:

```bash
just install
just check
```
