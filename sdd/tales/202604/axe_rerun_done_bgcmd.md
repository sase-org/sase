---
create_time: 2026-04-23 19:20:33
status: done
prompt: sdd/prompts/202604/axe_rerun_done_bgcmd.md
---
# Plan: `r` Re-run Keymap for Done Commands on AXE Tab

## Goal

Add a **re-run** affordance to the `sase ace` TUI on the **AXE tab**. When a done background-command entry (`BgCmdItem`
whose slot is no longer running) is selected, pressing `r` prompts the user with a y/n confirmation asking whether to
**dismiss the original entry before re-running**, and then re-runs the same command in a new slot (producing a new AXE
entry).

## Product Behavior

Selection state → what `r` does on the AXE tab:

| Selected item                                      | `r` behavior                                                              |
| -------------------------------------------------- | ------------------------------------------------------------------------- |
| `AxeParentItem`                                    | No-op (not shown in footer)                                               |
| `LumberjackItem`                                   | No-op (not shown in footer)                                               |
| `BgCmdItem` where `is_slot_running(slot)` is True  | No-op (not shown in footer — can't re-run something that's still running) |
| `BgCmdItem` where `is_slot_running(slot)` is False | Prompt y/n "Dismiss before re-running?" → re-run in a fresh slot          |

Confirmation modal outcomes:

- **y (Yes)** — clear the original done slot (same cleanup as the current `x` dismiss path for done bgcmds), allocate a
  new slot, start the command there. Selection moves to the new entry's view (same pattern as `_start_bgcmd`).
- **n (No)** — leave the original done slot in place, allocate a new slot, start the command there. Selection moves to
  the new entry.
- **escape / other** — cancel. Nothing happens (no re-run, no dismiss).

Edge cases:

- If all 9 slots are full (no available slot), surface the existing "Maximum background commands reached" error
  notification and do not dismiss. The y-answer should NOT clear the original if the subsequent re-run can't start.
- If the command info has vanished between selection and action (e.g. a polling race cleared it), no-op with no
  notification.

## Design Choice: Reuse `run_workflow` Action, Don't Add a New Binding

The `r` key is already bound globally to the `run_workflow` action (`src/sase/default_config.yml:29`). On the Agents tab
`run_workflow` dispatches to "resume agent"; on the CLs tab it shows the workflow picker; on the AXE tab it currently
early-returns (no-op). This is the established pattern: one key, one action, dispatched by tab + selection state
(compare `kill_agent`/`x`, which handles agent dismiss, bgcmd kill, lumberjack kill, and axe-parent start/stop from the
same action).

**Recommendation:** extend `action_run_workflow` with an AXE-tab branch that dispatches to a new `_rerun_bgcmd(slot)`
handler when the selection is a done `BgCmdItem`. **Do not** add a new `AppKeymaps` field or a new `default_config.yml`
entry.

Trade-off: a dedicated `rerun_bgcmd` action would be more self-documenting and user-rebindable, but it would collide
with `r` / `run_workflow` and force the user to pick a different default key. The selection-conditional dispatch is
consistent with the rest of the TUI and keeps the keymap surface small.

## Implementation Sketch (high-level — not a file diff)

1. **`src/sase/ace/tui/actions/axe_bgcmd.py`** — add a `_rerun_bgcmd(slot)` method on `AxeBgCmdMixin`:
   - Read `BackgroundCommandInfo` for the slot via `get_slot_info(slot)`; bail if None or if `is_slot_running(slot)` is
     True (defense-in-depth — the footer already hides the binding in these cases).
   - Check `find_first_available_slot()` up front. If None, notify and return without prompting (a prompt whose Yes path
     can fail is worse than no prompt).
   - Push a `ModalScreen[bool]`-style confirmation dialog whose message is
     `"Dismiss original entry before re-running?\n<command preview>"`, with y=True, n=False, esc=cancel (None). A new
     modal class is clearer than overloading `ConfirmKillModal`, whose title hardcodes "Kill Agent".
   - On y: call `clear_slot(original_slot)`, then start the new slot via
     `start_background_command(new_slot, command=info.command, project=info.project, workspace_num=info.workspace_num, workspace_dir=info.workspace_dir)`.
   - On n: same `start_background_command` call, no clearing.
   - After start: `_load_bgcmd_state()`, `_switch_to_axe_view(new_slot)`, emit a "Re-running: <cmd>" notification. If
     the y-path cleared the original slot, `_refresh_axe_display()` already fires via `_switch_to_axe_view`.
   - `cl_name` is not persisted in `BackgroundCommandInfo`, so the re-run cannot replay the checkout step. That matches
     the user's intent: they want the same command re-run in the same workspace, not a fresh CL checkout.

2. **`src/sase/ace/tui/actions/base.py`** — in `action_run_workflow`:
   - Before the `self.current_tab != "changespecs"` early return, add an `if self.current_tab == "axe"` branch that
     inspects `self._axe_items[self.current_idx]`. If it's a `BgCmdItem` whose slot is not running, call
     `self._rerun_bgcmd(slot)`. Anything else on the AXE tab: fall through to the existing early-return.

3. **`src/sase/ace/tui/modals/`** — add a small `ConfirmRerunModal(ModalScreen[bool | None])` (or reuse a generic
   confirm modal if we want to introduce one; inline for now to stay focused). Bindings: `y`=confirm(True),
   `n`=decline(False), `escape`/`q`=cancel(None). Export from the package `__init__`.

4. **`src/sase/ace/tui/widgets/keybinding_footer.py`** — extend `_compute_axe_bindings` to add the re-run binding when
   applicable:
   - Update the signature to accept an additional `selected_slot_done: bool = False` (or pass the full current item, but
     a bool is enough — the existing signature already reduces the item to `axe_current_view`).
   - When `selected_slot_done` is True, append `(self._kd("run_workflow"), "re-run")` to the bindings list, sorted
     alphabetically with the existing `x` kill entry per the CLAUDE.md footer convention.
   - Update every `update_axe_bindings(...)` call site (the app wires this in axe_display/axe mixins when selection
     changes) to pass the new flag. Grep `update_axe_bindings(` to find them.

5. **Help modal** — add a one-liner under the AXE tab section of `help_modal.py` for `r — re-run selected done command`
   to satisfy the `src/sase/ace/AGENTS.md` "Help Popup Maintenance" rule.

6. **Tests** — extend the existing `FakeAxeApp` pattern from `tests/ace/tui/test_axe_navigation.py`:
   - Unit test: `_rerun_bgcmd` on a running slot is a no-op; on a done slot with a full slot table notifies and does not
     clear; on a done slot with an available slot calls `start_background_command` with the saved
     command/project/workspace.
   - Unit test: `action_run_workflow` on the AXE tab with a selected done `BgCmdItem` dispatches to `_rerun_bgcmd`; with
     a running `BgCmdItem` or `AxeParentItem`/`LumberjackItem` it is a no-op.
   - Unit test: `_compute_axe_bindings` includes "re-run" exactly when the selected slot is done.
   - Stub `start_background_command` / `clear_slot` so no real processes or filesystem writes occur (follow the existing
     patching style in AXE tests).

## Out of Scope

- Persisting `cl_name` in `BackgroundCommandInfo` so that re-run can replay the CL checkout. Document this non-goal in
  the PR description; if we want it later it's a separate change to the `BackgroundCommandInfo` schema and
  `_start_bgcmd` call sites.
- Bulk re-run of multiple done entries.
- A generic reusable `ConfirmModal` across modals (still worthwhile cleanup, but not required for this feature).

## Validation Checklist

- `just check` passes (lint, mypy, tests).
- Manual smoke test: on the AXE tab, start a quick command (`sleep 1`), wait for it to finish, select the done entry,
  press `r`, press `y` → old entry gone, new running entry selected; repeat with `n` → old entry remains, new running
  entry selected; repeat with `esc` → nothing happens.
- Footer shows `r re-run` only when a done bgcmd is selected, never when running or on the axe parent.
- `?` help popup documents the new binding under the AXE section.
