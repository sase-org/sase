---
create_time: 2026-05-09 17:52:35
status: done
---
# Plan: Rename Agents Top-Bar Read Count Label to Done

## Goal

Change the human-readable metric label in the `sase ace` TUI Agents tab top info panel from `read` to `done`, so
completed agents that are no longer unread render as, for example, `2 done` instead of `2 read`.

## Current Behavior

The Agents tab top bar is rendered by `AgentInfoPanel` in `src/sase/ace/tui/widgets/agent_info_panel.py`.

The relevant metric is stored and passed internally as `read` / `_read_count`. It represents visible top-level agents in
the `Done` status bucket whose identities are not in `_unread_completed_agent_ids`. That count is computed in
`src/sase/ace/tui/actions/agents/_display_detail.py` and passed to `AgentInfoPanel.update_agent_counts(...)`.

There is a second compact panel-title surface in `src/sase/ace/tui/actions/agents/_display_panels.py` that renders short
chips such as `U1 D1`. The user request specifically says the `read` count text shown at the top of the Agents tab, so
this plan treats the top info panel label as the requested surface and leaves compact panel-title chips unchanged.

## Implementation

1. Update the display-label mapping in `AgentInfoPanel` so the metric key `read` renders with the label `done`.

2. Keep the internal metric key, argument name, and count variable as `read` for now. The code meaning is still
   "completed and already acknowledged/read", and renaming the internal API would widen the change without improving the
   user-visible behavior requested.

3. Preserve existing style behavior. The numeric count for the renamed label should continue using the current `read`
   style (`bold #5FD7FF`), so only the displayed word changes.

4. Update `tests/ace/tui/widgets/test_agent_info_panel.py` to assert the top-bar output uses `done` when `_read_count` /
   `read` is nonzero, and to update zero-metric assertions so they check that `done` is omitted where appropriate.

## Verification

Run the targeted widget test:

```bash
pytest tests/ace/tui/widgets/test_agent_info_panel.py
```

Because this repo’s memory requires full verification after source changes, run:

```bash
just install
just check
```

If `just check` is too slow or blocked by environment issues, report that explicitly with the targeted test result.
