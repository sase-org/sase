---
create_time: 2026-06-18 11:00:02
status: done
prompt: sdd/prompts/202606/agent_mark_auto_reads_unread.md
---
# Plan: Agents `m` Auto-Advance Acknowledges Unread Target

## Problem

On the Agents tab, pressing `m` toggles the mark state for the currently selected agent and then auto-advances to the
next visible agent row. When that next row is currently unread, it should become read as part of navigation, matching
normal `j`/`k` and mouse selection behavior.

Today this does not happen because `_toggle_mark_agent()` updates `current_idx` directly through
`_advance_mark_selection()`. That bypasses the normal selection/navigation side effects in:

- `EventWidgetHandlersMixin.on_agent_list_selection_changed()`
- `BasicNavigationMixin._navigate_agents_panel()`

Those paths handle unread behavior by arming manually unread rows when leaving them and acknowledging unread rows when
arriving at them.

## Scope

Keep this focused on Agents-tab mark auto-advance. No keymap changes are needed.

Expected touched areas:

- `src/sase/ace/tui/actions/agents/_marking.py`
- `tests/ace/tui/test_agent_marking.py`
- `tests/ace/tui/_agent_marking_helpers.py`

If the cleanest implementation requires a tiny shared helper in `AgentUnreadMixin` or navigation utilities, keep it
local to the existing unread/navigation contract and avoid changing unrelated rendering or notification projection code.

## Approach

1. Preserve the current mark/unmark behavior and visible-order auto-advance behavior.

2. Make the mark auto-advance path run the same unread side effects as other agent navigation:
   - Before moving away from the old selected agent, call the existing manual-unread departure hook when the mark action
     actually leaves that agent.
   - After advancing to the new selected agent, call the existing unread acknowledgment helper for the new agent when
     the selection lands on an agent row.
   - Do not acknowledge unread state for collapsed banner rows, although `m` already targets agent rows and
     `_advance_mark_selection()` walks visible agent rows only.

3. Keep rendering efficient:
   - Continue using `_try_patch_agent_row()` and `_refresh_panel_highlights()` for the old and new rows.
   - Avoid adding synchronous disk I/O or notification scanning to the key handler.
   - Reuse `_acknowledge_agent_unread()` so notification dismissal/cache invalidation stays in one place.
   - If acknowledgment already patches the new row, avoid unnecessary duplicate patching where practical; if patch
     ordering makes one extra selective row patch simpler, keep it selective and test the state outcome.

4. Add focused regression tests:
   - Marking an agent auto-advances to an unread `DONE` agent and clears that target from `_unread_completed_agent_ids`.
   - The old marked row remains marked and the new selected row gets patched/refreshed enough to reflect read/selected
     styling.
   - A manually unread target remains guarded on first arrival unless it has been armed by prior departure behavior,
     matching the existing manual unread contract.
   - Existing mark order and visible-order behavior continue to pass.

## Verification

Run targeted tests first:

```bash
pytest tests/ace/tui/test_agent_marking.py tests/ace/tui/test_agent_unread_selection.py tests/ace/tui/test_agent_unread_toggle.py
```

After implementation changes, run the repo-required check:

```bash
just check
```
