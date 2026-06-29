---
create_time: 2026-06-29 07:17:36
status: done
prompt: sdd/prompts/202606/close_admin_center_on_sase_update_confirm.md
---
# Close Admin Center After Full SASE Update Confirmation

## Goal

When the user opens SASE Admin Center, switches to the Updates tab, presses `S`, and confirms the full SASE update
prompt with `y`, close the SASE Admin Center immediately after confirmation instead of leaving it visible until the
update task completes and the TUI restarts.

## Current Behavior

The Updates tab is hosted by `ConfigCenterModal`, with the `S` key handled by `PluginsBrowserPane` via
`SaseUpdateActionsMixin`. The `S` flow opens a `PluginActionConfirmModal`; pressing `y` dismisses only that confirm
modal. Its callback then submits either the managed `uv tool upgrade sase` task or the dev checkout update task. The
parent `ConfigCenterModal` remains open while the background task runs.

This is different from the desired interaction: after the user has accepted the full update, the Admin Center is no
longer useful as a foreground panel because the update is already running and successful code changes will restart ACE.

## Scope

- Apply this only to the full SASE update action behind the Updates-tab `S` keymap.
- Cover both full-update variants:
  - managed install path: `Update SASE`
  - editable checkout path: `Update SASE dev checkouts`
- Do not change plugin install, uninstall, single-plugin update, or plugin update-all behavior. Those actions share
  `PluginActionConfirmModal`, so the dismissal must live in the `S`-specific callbacks rather than in the generic
  confirm modal.
- Do not change keymaps or default config.
- No Rust core changes are needed; this is TUI presentation/control-flow logic.

## Implementation Plan

1. Add a small SASE-update-specific helper in `src/sase/ace/tui/modals/plugins_browser_sase_update.py` that dismisses
   the containing `ConfigCenterModal` when it is still the pane's current screen. The helper should be defensive: if the
   screen is gone, not the Admin Center, or dismissal fails because the app is already transitioning, it should no-op.

2. Call that helper from the positive confirmation callbacks in `_open_managed_sase_update_modal()` and
   `_open_sase_dev_update_modal()`. The callback should still ignore `None` results so `n`, `q`, and `Esc` leave the
   Admin Center open exactly as they do today.

3. Preserve task submission ordering. Submit the update task first, then dismiss the Admin Center in the same callback.
   That keeps task startup owned by the mounted pane/app path, while still closing the panel immediately from the user's
   perspective.

4. Keep completion behavior unchanged. If the task later changes code, `_restart_after_update()` should continue to show
   the restart toast and call `_restart_tui(restart_axe=True)`. If the task is a no-op or fails, the toast should appear
   on the main TUI after the Admin Center has closed; the existing `self.is_mounted` guard will naturally skip an
   in-place Updates refresh for the dismissed pane.

## Test Plan

Add focused integration coverage in `tests/ace/tui/test_plugins_browser_pane_update.py`:

- Managed `S` path: open the Updates pane, open the managed full-update confirm modal, monkeypatch
  `_submit_sase_update_task()` to record submission without running a background worker, confirm with the modal action,
  then assert the submission happened and there is no modal left on screen.
- Dev `S` path: open the editable full-update confirm modal with a deterministic dev plan, monkeypatch
  `_submit_dev_update_task()` to record submission, confirm, then assert the submission happened and the Admin Center
  closed.
- Negative/cancel behavior if needed: cancel the `S` confirmation and assert `ConfigCenterModal` remains open on the
  Updates tab.

Run targeted tests first:

```bash
pytest tests/ace/tui/test_plugins_browser_pane_update.py
```

Because source files will be changed during implementation, run the repository checks before finishing:

```bash
just install
just check
```
