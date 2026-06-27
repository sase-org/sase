---
create_time: 2026-06-27 10:45:25
status: done
prompt: sdd/prompts/202606/split_operations_back.md
---
# Plan: Split Admin Center Operations Back Into Tasks and Logs Tabs

## Goal

Restore the SASE Admin Center to separate top-level **Logs** and **Tasks** tabs instead of the current combined
**Operations** tab with nested sub-tabs.

The target product shape is the pre-Operations Admin Center layout:

| Number | Tab      | Purpose                                 |
| ------ | -------- | --------------------------------------- |
| 1      | Config   | Layered SASE settings                   |
| 2      | Logs     | SASE log browser and launch failures    |
| 3      | Projects | Project lifecycle manager               |
| 4      | Tasks    | Background task monitor and live output |
| 5      | Updates  | SASE core and plugin updates            |
| 6      | XPrompts | XPrompt browser                         |

This is a runtime/UI revert, not a history rewrite. The old Operations plan remains historical SDD context, and this new
plan tracks the change back.

## Current State and Constraints

- Commit `192a4dc94` merged Tasks and Logs under `OperationsPane`.
- Current HEAD has later unrelated commits on top of that merge, including the five-stop Admin Center title gradient.
  Preserve those later changes.
- A dry reverse-patch check for `192a4dc94` only fails on the two Operations PNG goldens because the later
  title-gradient commit refreshed those images. Source files can be restored conceptually, but visual snapshots need
  deliberate regeneration.
- This work affects TUI navigation and rendering. Follow the existing TUI performance rules:
  - do not add synchronous work to event handlers;
  - preserve existing pane refresh/activity gates;
  - keep this a presentation/navigation change, not a backend behavior change.
- Do not restore the old standalone `,L` or `,t` leader keys. The desired state is separate Admin Center tabs with
  searchable command fast paths, matching the pre-Operations Admin Center behavior.

## Technical Design

### 1. Restore the six-tab Admin Center model

In `src/sase/ace/tui/modals/config_center_modal.py`:

- Change `CenterTab` back to: `config | logs | projects | tasks | updates | xprompts`.
- Replace the five-tab `_TAB_ORDER`, `_TAB_LABELS`, `_TAB_COLORS`, and `_TAB_DESCRIPTIONS` with the six-tab model:
  - `logs` uses the existing yellow log accent and description `Browse SASE logs and launch failures`.
  - `tasks` uses the existing green task accent and description `Monitor background tasks and live output`.
  - remove the `operations` tab label, color, and description.
- Remove `OperationsPane` / `OperationsSubTab` imports and import `LogsPane` and `TasksPane` directly.
- Remove the `initial_operations_subtab` constructor argument and stored field.
- In `compose()`, mount `LogsPane(id="logs")` and `TasksPane(id="tasks")` as direct children of
  `#config-center-switcher` in the tab order above.
- Update the module docstring and key-help wording from five tabs / Operations to six tabs / Logs / Tasks.
- Preserve the current five-stop `_TITLE_GRADIENT` and its comment from the later gradient commit.

Expected behavior:

- `#` still reopens the last used Admin Center tab from `app._admin_center_tab`.
- `1` through `6` jump to the six top-level tabs.
- `[` and `]` cycle through all six top-level tabs.
- Direct scroll forwarding (`g` / `G`) keeps working because Logs and Tasks are direct active panes again.

### 2. Remove the nested Operations pane

- Delete `src/sase/ace/tui/modals/operations_pane.py`.
- Remove the `OperationsPane` export/import from `src/sase/ace/tui/modals/__init__.py`.
- Remove `app._operations_subtab` initialization from `src/sase/ace/tui/actions/_state_init.py`.
- Remove the generic `subtab_host()` helper from `src/sase/ace/tui/modals/base.py` if no remaining code uses it.
- Remove Operations-specific CSS from `src/sase/ace/tui/styles.tcss`, while keeping the direct
  `ConfigCenterModal TasksPane` and `ConfigCenterModal LogsPane` sizing rules.

This returns Tasks and Logs to normal direct-pane activity detection and eliminates the nested `Tab` / `Shift+Tab`
navigation surface.

### 3. Restore Tasks and Logs pane direct activity checks

In `src/sase/ace/tui/modals/tasks_pane.py` and `src/sase/ace/tui/modals/logs_pane.py`:

- Remove `subtab_host()` imports and host checks.
- Restore `_is_active_tab()` to compare `screen._active_tab` directly to the pane id.
- Restore pane docstrings and hint text so they describe direct top-level tabs:
  - Logs hint should advertise `[ / ]: tab`, not `Tab: Tasks/Logs`.
  - Tasks hint should advertise normal top-level tab cycling and should not mention Tasks/Logs sub-tabs.

This keeps existing polling/focus gating simple: a pane is active only when its direct Admin Center tab is active.

### 4. Restore command fast paths and user-facing copy

In `src/sase/ace/tui/actions/base.py`:

- `action_open_log_panel()` should push `ConfigCenterModal(initial_tab="logs")`.
- `action_open_tasks_panel()` should push `ConfigCenterModal(initial_tab="tasks")`.
- Update docstrings to say Logs tab and Tasks tab.

In command/help metadata:

- Remove the `"operations"` alias from `open_config_center` in `src/sase/ace/tui/commands/_app_metadata.py`.
- Keep `logs`, `tasks`, and `task queue` aliases.
- Update `src/sase/ace/tui/commands/catalog.py` docstrings back to "Logs tab" and "Tasks tab".
- Update help binding tables in `src/sase/ace/tui/modals/help_modal/*_bindings.py` from `1-5` to `1-6` where the Admin
  Center numeric-tab help was changed.
- Restore log failure hints in `src/sase/ace/tui/actions/failure_messages.py` to point to
  `Logs in SASE Admin Center (#)`.
- Restore related comments/docstrings in `axe_chop_run.py`, `axe_display/_render.py`, `logs/__init__.py`, and
  `logs/sources.py` where they currently say `Operations / Logs`.

### 5. Update tests back to the six-tab contract

Remove Operations-specific tests:

- Delete `tests/ace/tui/test_operations_pane.py`.

Restore or update existing tests:

- `tests/ace/tui/test_config_center_tabs.py`
  - assert tab cells: `1 Config`, `2 Logs`, `3 Projects`, `4 Tasks`, `5 Updates`, `6 XPrompts`;
  - update digit-hotkey tests so `2` is Logs, `4` is Tasks, `5` is Updates, `6` is XPrompts;
  - update remembered-tab tests to use direct `logs` or `tasks`;
  - update fast-path tests so `action_open_log_panel()` remembers `logs` and no `_operations_subtab` exists.
- `tests/ace/tui/test_logs_pane.py` and `tests/ace/tui/test_tasks_pane.py`
  - open `ConfigCenterModal(initial_tab="logs")` or `initial_tab="tasks"` directly;
  - restore bracket-navigation expectations for six top-level tabs.
- `tests/ace/tui/test_log_panel_keymap.py`, `tests/ace/tui/test_projects_pane.py`,
  `tests/ace/tui/test_plugins_browser_pane_loading.py`, and adjacent launch/failure tests
  - update comments, expected strings, and top-level tab numbers to the six-tab layout.
- `tests/test_command_catalog.py` and `tests/test_keymaps_defaults.py`
  - restore command/search/help expectations from Operations wording to direct Logs/Tasks wording.

### 6. Restore visual snapshot coverage

In `tests/ace/tui/visual/_ace_config_center_png_snapshot_helpers.py`:

- `_open_logs_modal()` should use `ConfigCenterModal(initial_tab="logs")`.
- `_open_tasks_modal()` should use `ConfigCenterModal(initial_tab="tasks")`.

In the visual tests:

- Rename snapshot IDs/titles back to:
  - `config_center_logs_tab_120x40`, title `ACE SASE Admin Center - Logs Tab`
  - `config_center_tasks_tab_120x40`, title `ACE SASE Admin Center - Tasks Tab`
- Restore the PNG golden files with the current five-stop title gradient:
  - add `tests/ace/tui/visual/snapshots/png/config_center_logs_tab_120x40.png`
  - add `tests/ace/tui/visual/snapshots/png/config_center_tasks_tab_120x40.png`
  - remove `config_center_operations_logs_120x40.png`
  - remove `config_center_operations_tasks_120x40.png`

Do not roll back the other Admin Center PNGs that were refreshed by the five-stop title-gradient change. Only the
Logs/Tasks snapshot filenames and rendered tab layout should change for this revert.

## Implementation Approach

Use targeted edits rather than a hard reset or history rewrite.

A raw `git revert 192a4dc94` is tempting, but it is not ideal as the only plan because later commits changed the
Operations PNGs. It would also mechanically flip historical SDD plan metadata unless carefully handled. The safer
approach is:

1. Restore the relevant source and test behavior to the pre-Operations shape, using `192a4dc94^` as a reference.
2. Manually preserve later unrelated changes, especially the five-stop title gradient.
3. Regenerate only the affected visual snapshots under the restored Logs/Tasks names.
4. Leave the original Operations SDD plan as historical context and rely on this new plan for the revert.

## Validation Plan

Before validation, run `just install` per the ephemeral-workspace rule.

Then run:

```bash
just fmt
pytest tests/ace/tui/test_config_center_tabs.py \
  tests/ace/tui/test_logs_pane.py \
  tests/ace/tui/test_tasks_pane.py \
  tests/ace/tui/test_log_panel_keymap.py \
  tests/test_command_catalog.py \
  tests/test_keymaps_defaults.py
just test-visual
just check
```

Expected visual workflow:

- First `just test-visual` may fail on missing/changed Logs/Tasks goldens.
- Inspect the generated `.pytest_cache/sase-visual/` actual/diff artifacts to confirm:
  - top-level tabs are `Config Logs Projects Tasks Updates XPrompts`;
  - active Logs and Tasks tabs render directly, without a nested Operations strip;
  - title gradient remains the five-stop version.
- Accept only the intended Logs/Tasks snapshot changes with `--sase-update-visual-snapshots`.
- Re-run `just test-visual`, then `just check`.

## Non-Goals

- Do not restore standalone Logs or Tasks modal classes.
- Do not restore retired `,L` or `,t` leader key bindings.
- Do not change task queue, log source loading, or backend behavior.
- Do not change the Admin Center title gradient, border color, or unrelated plugin/project/xprompt panes.

## Risks and Mitigations

- **Risk: losing later visual-gradient work.** Mitigation: preserve `_TITLE_GRADIENT` in source and regenerate
  Logs/Tasks goldens from current HEAD behavior.
- **Risk: stale Operations references in tests or user-facing hints.** Mitigation: search for `Operations / Logs`,
  `Operations / Tasks`, `initial_operations_subtab`, `_operations_subtab`, and `config_center_operations_` after edits.
- **Risk: accidental reintroduction of leader keys.** Mitigation: keep keymap retirement tests and comments aligned with
  direct Admin Center tabs, not standalone panels.
- **Risk: event-loop or refresh regressions.** Mitigation: remove nested routing and restore direct pane
  `_is_active_tab()` checks without adding new I/O or async pathways.
