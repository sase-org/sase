---
create_time: 2026-06-01 10:42:11
status: done
prompt: sdd/prompts/202606/fix_axe_chop_edit.md
---
# Plan: Fix `sase ace` crash when pressing `e` on AXE chop output

## Problem

Pressing `e` on the AXE tab currently dispatches to `AgentPanelDetailMixin.action_edit_spec`. That method only handles
the Agents tab specially; every non-Agents tab falls through to `ChangeSpecMixin.action_edit_spec`. On AXE,
`current_idx` is the AXE sidebar row index, not a ChangeSpec index, so `self.changespecs[self.current_idx]` can raise
`IndexError`.

The user-facing intent in this case is to open the selected chop run output in `$EDITOR`. The AXE tab already has chop
selection state and per-run output metadata, but `edit_spec` does not route to it.

## Approach

1. Add an AXE-specific branch to `AgentPanelDetailMixin.action_edit_spec`.
   - Keep existing behavior for Agents: open selected or marked agent chats.
   - Keep existing behavior for ChangeSpecs: call the parent implementation.
   - For AXE: call a new helper that attempts to open the currently displayed chop run log.

2. Implement a small AXE helper near the other AXE/chop action code.
   - Derive the AXE selection before reading it, so a recently moved cursor is handled even if the debounced paint has
     not run yet.
   - Require a selected `ChopItem`; lumberjack and bgcmd rows should no-op with a warning.
   - Resolve the displayed run index with `_axe_resolve_chop_run_offset`, matching the run shown by the dashboard after
     `Ctrl+N` / `Ctrl+P`.
   - If the chop has no recorded runs, notify instead of launching an editor.
   - Use `sase.axe.state.chop_run_log_path(lumberjack, chop, run_id)` to open the persisted log file directly in
     `$EDITOR` under `self.suspend()`.
   - If the log path is missing, notify instead of crashing.

3. Tighten ChangeSpec indexing defensively.
   - Update `ChangeSpecMixin.action_edit_spec` to guard `0 <= current_idx < len(changespecs)`.
   - This is not the primary fix, but it prevents the same shared-index failure mode from turning into an app crash if
     another path dispatches to the ChangeSpec action with stale state.

4. Update discoverability and command availability.
   - Adjust the command catalog label for `edit_spec` so AXE usage is represented as "spec / chat / chop output".
   - Update AXE command availability so `app.edit_spec` is only available when the AXE item is a chop with a recorded
     run, not on arbitrary AXE rows.
   - Add `e` to AXE help/footer bindings when a chop run exists, labelled as opening/editing output.

5. Add focused tests.
   - Unit-test the AXE edit helper with a fake app: selected chop opens the correct persisted log path for newest and
     offset-selected runs.
   - Unit-test no-crash notifications for no selected chop and chop with no runs.
   - Unit-test command availability for AXE `edit_spec`: available on chop rows with runs, unavailable on
     lumberjack/bgcmd/no-run cases.
   - Unit-test the defensive ChangeSpec `current_idx` guard if no existing test covers it.

6. Verify.
   - Run the focused pytest targets for the new/changed behavior.
   - Because source files will change, run `just check` after `just install` if the workspace needs dependencies
     refreshed.

## Expected outcome

Pressing `e` on a selected AXE chop row opens the currently displayed run log in the configured editor. Pressing `e` on
AXE rows where no chop run output exists shows a warning and leaves the TUI running. The ChangeSpec action no longer
crashes on stale or cross-tab indices.
