---
create_time: 2026-06-28 15:26:32
status: done
prompt: sdd/prompts/202606/persist_admin_center_tab.md
---
# Persist Admin Center Tab Selection

## Goal

Remember the last focused SASE Admin Center tab across TUI restarts. Today the Admin Center writes the active tab to
`app._admin_center_tab`, which survives only for the current Textual app session. After this change, pressing `#` in a
fresh TUI should open the Admin Center on the most recently selected tab from a previous TUI run.

## Current Behavior

- `ConfigCenterModal` owns the internal Admin Center tab state as `_active_tab`.
- `ConfigCenterModal._remember_active_tab()` copies `_active_tab` to the long-lived app field `app._admin_center_tab`.
- `BaseActionsMixin.action_open_config_center()` reads `app._admin_center_tab` and uses it as
  `ConfigCenterModal(initial_tab=...)`.
- Fast paths such as logs, projects, and tasks still open a specific tab by passing `initial_tab` directly; once the
  modal mounts, that tab is remembered in the current app session.
- `_init_app_state()` currently seeds `_admin_center_tab` to `"config"` during construction.

## Design

Add a small TUI preference helper for the Admin Center active tab, using the same style as existing bounded per-user
state helpers such as last query and last agent selection.

- Store one JSON or text file under `sase_home()`, for example `admin_center_state.json` or `admin_center_tab.txt`.
- The persisted schema should be intentionally tiny: a single tab string is enough for this feature. If JSON is used,
  prefer a version-friendly shape such as `{"active_tab": "logs"}`.
- Reads must validate the tab against the Admin Center tab set and fall back to `"config"` for missing, unreadable,
  malformed, or stale values.
- Writes should be best-effort and should never surface user-facing errors for a preference failure.

This is TUI presentation state, not shared domain behavior. It should remain in the Python TUI/ACE layer rather than
moving into the Rust core backend.

## Implementation Shape

1. Add a focused persistence module, likely under `src/sase/ace/`, with helpers along these lines:
   - `load_admin_center_tab(valid_tabs: Collection[str]) -> str | None`
   - `save_admin_center_tab(tab: str, valid_tabs: Collection[str]) -> bool`
   - a module-level test override for the backing file, matching existing patterns like `_LAST_SELECTION_FILE`.

2. Initialize the app field from disk:
   - In `_init_app_state()`, replace the hard-coded `self._admin_center_tab = "config"` with a validated persisted read
     and a fallback to `"config"`.
   - Keep this read pure and cheap. It is a single small file read during app construction, before widgets exist.

3. Persist changes when the Admin Center active tab changes:
   - Keep the current in-memory assignment in `_remember_active_tab()`.
   - Avoid synchronous disk I/O on tab-switch handlers. Either schedule a small thread-backed write after the UI state
     has been updated, or provide an app method that records the in-memory tab immediately and delegates persistence
     off-thread.
   - Coalesce or tolerate duplicate writes from mount and repeated tab switches. This preference file is tiny, so
     correctness and event-loop safety matter more than elaborate batching.

4. Preserve fast-path semantics:
   - `action_open_log_panel()`, `action_open_projects_panel()`, and `action_open_tasks_panel()` should still force their
     requested tab.
   - Opening through those fast paths should update both the in-memory field and persisted state once the modal mounts,
     so a later plain `#` reopens on that fast-path tab.
   - `action_open_config_center()` should continue using the app field, which is now seeded from disk.

5. Keep tab validation centralized enough that adding a future Admin Center tab only requires updating the Admin Center
   tab order and tests, not hunting for duplicated literals in persistence code.

## Tests

Add focused persistence-unit coverage:

- missing file returns `None`;
- malformed JSON/text returns `None`;
- unknown tab returns `None`;
- valid tab round-trips;
- write rejects unknown tabs without corrupting state.

Extend Admin Center/TUI behavior coverage:

- construct an app or action harness with a persisted `"updates"` tab and assert `action_open_config_center()` pushes
  `ConfigCenterModal(initial_tab="updates")`.
- open Admin Center in an `AcePage`, switch to another tab, close the modal, create a fresh app/session with the same
  isolated `SASE_HOME`, press `#`, and assert the modal opens on the persisted tab.
- cover the fast-path case: open Logs/Tasks/Projects, close, start a fresh app using the same isolated state, then plain
  `#` opens on that fast-path tab.
- keep the existing session-memory test, but update expectations so it also verifies persistence where appropriate.

## Performance And Reliability

- Do not write the preference file synchronously from `ConfigCenterModal` action handlers or click handlers; those are
  on the Textual event loop.
- A single small startup read is acceptable, but it must not touch widgets or perform any expensive scan.
- Persistence failures should be silent and must not block tab switching, modal close, or fast-path opens.
- If an off-thread write races with another tab change, last write should win. Because the app field is updated
  immediately, in-session behavior remains correct even if disk persistence lags briefly.

## Validation

After implementation, run targeted tests first:

```bash
pytest tests/ace/tui/test_config_center_tabs.py tests/ace/tui/test_log_panel_keymap.py
```

Then run the repo-required check sequence after installing the workspace:

```bash
just install
just check
```
