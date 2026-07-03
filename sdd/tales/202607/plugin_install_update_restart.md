---
create_time: 2026-07-03 16:52:05
status: done
prompt: sdd/prompts/202607/plugin_install_update_restart.md
---
# Plan: Restart TUI + AXE when installing/updating individual plugins

## Problem

The bulk `u` keymap on the Admin Center Updates tab already restarts ACE (the TUI) and AXE after a successful
`sase update`: it writes a post-restart toast receipt, re-execs `sase ace --restart-axe`, and the fresh process restarts
the AXE daemon and shows a "✓ Updated" confirmation toast.

Individual plugin operations do not behave uniformly. After an install (and, on the CLI, after any plugin operation) the
running TUI and AXE keep executing stale code: newly installed plugin hooks, xprompts, CLI/TUI surfaces, and entry
points are invisible until the user manually restarts.

### Current behavior at HEAD (survey)

| Flow                                              | Restart today?             | Post-restart toast receipt?                                             |
| ------------------------------------------------- | -------------------------- | ----------------------------------------------------------------------- |
| TUI Updates tab `u` (sase + all plugins, managed) | TUI + AXE                  | yes                                                                     |
| TUI Updates tab `u` (dev/editable)                | TUI + AXE                  | yes                                                                     |
| TUI Updates tab `U` (single plugin, managed)      | TUI + AXE                  | **no** (restarts without receipt → no confirmation toast after restart) |
| TUI Updates tab `U` (single plugin, dev/editable) | TUI + AXE                  | yes (reuses the bulk completion handler)                                |
| TUI Updates tab `i` (install plugin)              | **no**                     | no                                                                      |
| TUI Updates tab `x` (uninstall plugin)            | **no**                     | no                                                                      |
| CLI `sase update`                                 | AXE (inline, when changed) | n/a                                                                     |
| CLI `sase plugin install/update/uninstall`        | **no**                     | n/a                                                                     |

Key machinery (all pure Python; no Rust core involvement anywhere in these paths):

- Reference completion handler: `_handle_code_update_completion` in
  `src/sase/ace/tui/modals/plugins_browser_sase_update.py` — on a real change it calls `build_update_receipt` +
  `write_pending_update_toast` (`src/sase/ace/update_receipt.py`), then `_restart_after_update` →
  `app._restart_tui(restart_axe=True)`.
- TUI restart: `_restart_tui` (`src/sase/ace/tui/actions/axe.py`) sets `AceExitAction.RESTART_TUI_AND_AXE`;
  `src/sase/main/ace_handler.py` then `os.execv`s `sase ace --restart-axe`, and the _new_ process restarts the AXE
  daemon on startup and consumes the pending toast receipt (`src/sase/ace/tui/actions/post_update_toast.py`).
- CLI AXE restart: `restart_after_update` in `src/sase/main/update_restart.py`, used only by `sase update`
  (`src/sase/main/update_handler.py`), skipped when nothing changed or AXE is not running.
- All plugin install/update/uninstall execution (TUI and CLI) funnels through the shared operations layer
  `src/sase/plugins/operations.py`; every outcome type (`InstallOutcome`, `UpdateOutcome`, `UninstallOutcome`) carries a
  `UvChangeSet`, so "did code actually change?" is answerable uniformly via the existing `managed_update_changed`
  predicate.

## Goals

1. TUI plugin **install** (`i`) restarts TUI + AXE after a successful install that changed the environment, exactly like
   `u`/`U`, including a post-restart confirmation toast.
2. TUI single-plugin **update** (`U`, managed path) gains the missing toast receipt so it is fully consistent with the
   bulk flow (it already restarts).
3. TUI plugin **uninstall** (`x`) restarts TUI + AXE too (recommended: stale plugin code staying loaded after removal is
   the same problem in reverse — hooks/panels appear available but the package is gone). This step is separable if you
   want to keep `x` restart-free.
4. CLI parity: `sase plugin install`, `sase plugin update`, and `sase plugin uninstall` restart AXE inline when the uv
   run changed packages, mirroring `sase update` (the CLI cannot restart a TUI it isn't running in).
5. No behavior change when nothing changed: no-op installs/updates keep today's toast-and-refresh behavior with no
   restart.

## Non-goals

- Notifying an already-running TUI when a _CLI_ plugin operation changes the environment (the Updates indicator already
  covers staleness signaling; cross-process TUI restart is out of scope).
- New CLI flags (e.g. `--no-restart`). `sase update` restarts unconditionally on change; plugin commands should match
  that established behavior rather than grow new surface.
- Any Rust core (`sase-core`) changes. Restart/re-exec is process/presentation machinery per the existing boundary note
  in `src/sase/ace/update_receipt.py`, and the shared plugin operations layer already lives in Python.

## Design

### 1. TUI: route install/uninstall completions through the shared restart machinery

`PluginsBrowserPane` already composes `SaseUpdateActionsMixin` (which owns `_restart_after_update` and the receipt
writing) together with the install/uninstall/update mixins, so the success branches just need to converge:

- `_on_install_complete` (`src/sase/ace/tui/modals/plugins_browser_install.py`): when the payload reports a real change
  (`managed_update_changed`), build + write a toast receipt for the `InstallOutcome`, then
  `_restart_after_update(completion.message)`. Unchanged installs keep the current toast + in-place row refresh.
- `_on_uninstall_complete` (`src/sase/ace/tui/modals/plugins_browser_uninstall.py`): same shape for `UninstallOutcome`
  (goal 3).
- `_on_update_complete` (`src/sase/ace/tui/modals/plugins_browser_update.py`): before its existing
  `_restart_after_update` call, build + write the receipt for the single-plugin `UpdateOutcome` (fixes the missing
  post-restart toast).

Consider extracting the small "receipt + restart if changed, else toast + refresh" sequence into a shared helper on the
sase-update mixin so all four completion handlers stay one-liner-thin, rather than duplicating the sequence per mixin.

Deliberate choices:

- Keep the Updates pane open after confirming a single-plugin action (unlike the bulk `u` flow, which dismisses the
  Admin Center). Single-plugin operations can legitimately no-op, and the in-place row refresh is valuable in that case;
  on success the restart tears everything down anyway. `_restart_after_update` already warns about background tasks that
  will be stopped.
- Mention the restart in the confirm modals so it is never a surprise: add a line to the install/update/uninstall
  `PluginActionConfirmModal` summaries (e.g. "ACE restarts after a successful install to load the new plugin").

### 2. Extend the post-restart toast receipt to per-plugin outcomes

`build_update_receipt` (`src/sase/ace/update_receipt.py`) currently accepts only the bulk `UpdateSummary` and
`DevUpdateResult` payloads. Extend it (or add sibling builders) to normalize the plugin-operations outcomes:

- `InstallOutcome` → one plugin transition with `old=None`, `new=<installed version>`.
- `UpdateOutcome` (from `sase.plugins.operations`; note the name collides with the per-package
  `sase.uv_tool.render.UpdateOutcome` — keep imports explicit) → transitions for upgraded targets.
- `UninstallOutcome` → one transition with `new=None` (only if goal 3 stays in scope).

The on-disk format needs no version bump: transitions already allow a missing `old` or `new`, and `kind="managed"` still
applies. Older readers parse these receipts fine.

Rendering (`src/sase/ace/tui/actions/post_update_toast.py`) needs small wording upgrades so install/uninstall receipts
read naturally instead of "unknown → 1.2.3":

- `old=None` → render as an install ("• sase-foo installed v1.2.3"), title "✓ Installed sase-foo".
- `new=None` → render as a removal, title "✓ Uninstalled sase-foo".
- Single-plugin update with no sase primary → title should name the plugin rather than the current fallback "✓ SASE
  updated".

### 3. CLI: restart AXE inline for plugin install/update/uninstall

Mirror `sase update`'s injectable pattern in the three CLI handlers (`src/sase/plugins/cli_install.py`, `cli_update.py`,
`cli_uninstall.py`):

- After a successful live run whose change set reports a real change, call
  `restart_after_update(changed=..., axe_running_fn=is_axe_running, restart_axe_fn=restart_axe_daemon_result)` and
  render via `render_restart_info` (`src/sase/main/update_restart.py`). Dry runs and no-op outcomes skip it entirely,
  and AXE-not-running is already handled inside the helper.
- Keep both functions injectable through the handler signatures so the handlers stay unit-testable without a daemon,
  matching `handle_update_command`.
- `-j|--json` payloads gain a `restart` object shaped like `sase update`'s (`RestartInfo` serialization in
  `src/sase/main/update_json.py`). This is additive, so the per-command JSON schema version constants do not need a
  bump.
- No new CLI options, so no parser/help changes beyond documenting the restart in the subcommand help text
  (`src/sase/main/parser_plugin.py` descriptions).

### 4. User-facing text and docs

- Update the Updates-pane hints/detail text and the Admin Center help content wherever `i`/`U`/`x` behavior is
  described, so the automatic restart is documented (per the repo rule that `?` help stays in sync with behavior).
- The pre-restart notification path (`_restart_after_update`) already produces "<message> — restarting ACE to load new
  code. N background tasks will be stopped." and the prompt-draft stash notice; no changes needed there.

## Testing

TUI (extend the existing pane suites, which already monkeypatch `_restart_tui` and assert `restart_calls`):

- `tests/ace/tui/test_plugins_browser_pane_install.py`: successful install → `restart_calls == [True]` and a receipt
  written (use the receipt-file test override); no-change install → no restart, toast + refresh preserved; failed
  install → no restart.
- `tests/ace/tui/test_plugins_browser_pane_update.py`: managed single-plugin update now also writes a receipt (the
  restart assertions already exist).
- `tests/ace/tui/test_plugins_browser_pane_uninstall.py`: mirror the install assertions (goal 3).

Receipt + toast:

- `tests/ace/test_update_receipt.py`: round-trip the new payload types, including `old=None` / `new=None` transitions.
- `tests/ace/tui/test_post_update_toast.py`: install/uninstall/single-plugin wording and titles.
- PNG snapshots: the post-update toast has visual goldens
  (`tests/ace/tui/visual/test_ace_png_snapshots_post_update_toast.py`); new toast variants likely need new goldens via
  `just test-visual` (accept intentional changes with `--sase-update-visual-snapshots`).

CLI:

- `tests/test_plugin_cli_install.py` / `test_plugin_cli_update.py` / `test_plugin_cli_uninstall.py`: restart invoked
  with injected fakes when the change set changed; skipped for dry-run, no-op, and AXE-not-running; JSON payload
  includes the `restart` object; human output renders the existing "Axe Restart" panel.

## Risks / edge cases

- Restarting on install kills running tracked tasks; the existing warning toast covers this, and the confirm-modal
  wording change makes the tradeoff visible before the user commits.
- A plugin installed "from git" vs "from index" flows through the same `InstallOutcome`, so both modal variants get the
  restart for free.
- Uninstall restart (goal 3) is the only behavior a user might plausibly _not_ want (removing a plugin they weren't
  using anyway). If that feels too aggressive, drop that step; everything else stands alone.

## Sequencing

1. Receipt/toast extension for per-plugin outcomes (`update_receipt.py`, `post_update_toast.py`) + unit tests — unblocks
   everything else.
2. TUI install (and uninstall) restart wiring + receipt for the managed `U` path + pane tests + modal/help wording.
3. CLI AXE-restart parity + CLI tests + help text.
4. Visual snapshot goldens for the new toast variants.
