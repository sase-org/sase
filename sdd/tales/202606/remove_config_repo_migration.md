---
create_time: 2026-06-29 12:56:23
status: done
prompt: sdd/prompts/202606/remove_config_repo_migration.md
---
# Remove the Config-tab `g` "Migrate repos" keymap and its migration logic

## Goal

Remove the one-key `sibling_repos` → `linked_repos` migration feature from the `sase ace` Config Center. This is the `g`
keymap on the **Config** tab and all the code that exists solely to support it. The feature is no longer wanted.

## Scope decision: migration feature vs. deprecated-key support

There are two distinct, separable concerns in the codebase, and only the first is in scope:

1. **The migration feature (REMOVE).** The interactive, user-triggered flow that folds a writable file's `sibling_repos`
   list into `linked_repos` and deletes `sibling_repos`. Its only entry points are the Config tab's `g` keymap and a
   special-case in the field-edit action. Nothing runs it automatically.

2. **Deprecated-key support (KEEP — out of scope).** `sibling_repos` remains a recognized, still-honored _deprecated
   alias_ for `linked_repos`. This is a broader backward-compatibility surface that the migration feature is layered on
   top of, but is independent of it. It must continue to work so existing user configs that still set `sibling_repos`
   keep functioning. Specifically, leave untouched:
   - The `sibling_repos` definition in `config/sase.schema.json` (deprecated alias).
   - `DEPRECATED_TOP_LEVEL_KEYS` and `_collect_deprecated_keys` in `src/sase/config/core.py` (drives the "this key is
     deprecated; use `linked_repos`" warning).
   - The runtime merge of `linked_repos` + `sibling_repos` in `src/sase/linked_repos.py`.
   - The `src/sase/sibling_repos.py` backward-compat re-export module.
   - The deprecation tests in `tests/test_config.py` and `tests/test_config_schema.py`.

   Note: the `sibling_repos` symbols in `src/sase/llm_provider/commit_finalizer*` and
   `src/sase/axe/run_agent_runner_setup.py` are an **unrelated** concept (dirty sibling repositories during a commit)
   and must not be touched.

3. **Rust core: no changes.** Investigation confirmed the Rust core (`sase-core`) contains no migration logic. It only
   tracks deprecation _warnings_ via a `deprecations` map passed in from Python. The entire migration transform lives in
   Python. This change does not cross the Rust core backend boundary.

## Behavioral outcome

- The Config tab no longer binds `g`. After removal, `g` falls through to the Config Center's shared `on_key` handler,
  which only acts when the active pane exposes `action_scroll_to_top` — the Config pane does not, so `g` becomes an
  inert no-op there (consistent with it doing nothing today on a config with no `sibling_repos` set).
- Selecting the `sibling_repos` field and pressing `e`/Enter now opens the **normal** field editor (like any other
  deprecated-but-editable key) instead of launching the migration modal.
- `ConfigEditModal` becomes a single-purpose field editor (no "migration mode").
- Users who still want to move `sibling_repos` into `linked_repos` can do so by editing both fields directly in the
  Config tab; the deprecation warning still guides them.

## Changes

### 1. Config pane widget — remove the entry points

File: `src/sase/ace/tui/modals/config_pane_widget.py`

- Delete the `("g", "migrate", "Migrate repos")` entry from `BINDINGS`.
- Delete the `action_migrate()` method.
- Delete the `_open_migration()` method.
- In `action_edit_field()`, remove the `sibling_repos`/`is_modified` special case that calls `_open_migration()`, so the
  method just opens the normal editor for any selected leaf. Update its docstring (drop the "or migrate" clause).
- In `_hints()`, remove `g: migrate` from the hint string.

### 2. Config edit modal — drop "migration mode" entirely

File: `src/sase/ace/tui/modals/config_edit_modal.py`

The modal currently doubles as the migration UI via a `mode` parameter. Collapse it to a field-only editor:

- Remove the `for_migration()` classmethod.
- Remove the `mode` parameter from `__init__`, the `self._mode` attribute, and simplify the
  `if mode == "field" and field is not None` guard to just check `field`.
- In `_initialize()`, remove the `if self._mode == "migration": self._begin_migration()` branch.
- Delete the `_begin_migration()` method.
- In `_start_plan()`, remove the early `if self._mode == "migration": return`.
- In `action_toggle_reset()`, drop the `or self._mode == "migration"` guard.
- In `action_back()`, simplify `if self._stage == "preview" and self._mode == "field"` to `if self._stage == "preview"`.
- In `_on_plan_worker()`, remove the migration branches. With migration gone, the planning worker always returns a real
  `EditPlanResult`, so the `if result is None:` block (and its "nothing to migrate" message) is dead code and should be
  removed; the error branch collapses to the field path.
- Remove `plan_repo_key_migration` from the `from sase.config import (...)` import.
- Remove `Mode` from the `config_edit_types` import; update the class docstring (drop "or run the repo-key migration").

### 3. Config edit rendering — remove migration-specific rendering

File: `src/sase/ace/tui/modals/config_edit_rendering.py`

- Remove the `_mode: Mode` base-class annotation and the `Mode` import.
- Simplify the two `self._mode == "field" and ...` compose guards to be unconditional.
- In `_focus_editor()`, drop the `or self._mode == "migration"` guard.
- Remove the migration branches in `_title()`, `_info_text()`, `_value_text()`, and `_hints()` (the "Migrate
  sibling_repos → linked_repos" title, the fold-and-remove info line, the empty-value short-circuit, and the migration
  hint string).

### 4. Config edit types — remove the Mode literal

File: `src/sase/ace/tui/modals/config_edit_types.py`

- Remove `Mode = Literal["field", "migration"]` (no longer referenced once the modal/rendering changes land).

### 5. Config edit backend — remove the migration planner

File: `src/sase/config/edit.py`

- Delete `plan_repo_key_migration()` and its private helper `_migration_target_layer()`, plus the "Deprecated-key
  migration" section comment.
- The helpers it reused (`plan_config_edit`, `unset_key`, `_unified_diff`, `dataclasses`, `Path`) are all still used
  elsewhere in the module and stay.

File: `src/sase/config/__init__.py`

- Remove the `plan_repo_key_migration` re-export (both the import and the `__all__` entry).

### 6. Tests — remove migration tests; keep deprecation tests

- `tests/ace/tui/test_config_pane_widget.py`: remove `test_config_pane_migrate_opens_migration_modal`. Optionally add a
  small regression test asserting the Config pane no longer binds `g` (e.g. `_binding_action("g") is None`) and that
  editing `sibling_repos` opens a normal `ConfigEditModal` rather than a migration modal.
- `tests/ace/tui/test_config_edit_modal_widget.py`: remove `test_migration_writes_linked_and_removes_sibling` and its
  section comment; update the module docstring to drop the migration sentence. The `sibling_repos` entry in the test
  schema may remain (harmless) or be dropped.
- `tests/test_config_edit.py`: remove `test_plan_repo_key_migration_folds_and_removes`,
  `test_plan_repo_key_migration_none_when_not_set`, the `_migration_inventory` helper, the `_MIGRATION_SCHEMA` fixture,
  the section comment, and the `plan_repo_key_migration` import (all used only by these tests).
- Do NOT remove the `sibling_repos` deprecation tests in `tests/test_config.py` or the
  `["linked_repos", "sibling_repos"]` parametrization in `tests/test_config_schema.py` — those cover deprecated-key
  support, which stays.

### 7. PNG visual snapshots — regenerate Config-tab goldens

The Config pane's hint line is captured by the Config Center PNG snapshots, so removing `g: migrate` from `_hints()`
will change them.

- Regenerate the affected goldens under `tests/ace/tui/visual/snapshots/png/` for
  `tests/ace/tui/visual/test_ace_png_snapshots_config_center_config.py` using
  `just test-visual --sase-update-visual-snapshots`, then visually confirm the only change is the removed `g: migrate`
  text before accepting.

## Explicitly NOT changed

- The help modal (`help_modal.py`) and keybinding footer (`keybinding_footer.py`) — the migrate keymap was never
  documented there, so per the ACE help-sync rule there is nothing to update.
- Historical SDD artifacts that mention the feature in passing (past `sase_plan_*.md` plan logs and `sdd/research/`,
  `sdd/epics/` docs) are point-in-time records and are intentionally left as-is.

## Verification

- `just install` then `just check` (lint + mypy + tests). Pay attention to any newly-unused imports flagged by ruff in
  the edited modules.
- `just test-visual` after regenerating goldens to confirm the Config-tab snapshots pass.
- Manual sanity check in `sase ace` → Config tab: `g` does nothing; editing the `sibling_repos` field opens the normal
  editor; editing other fields and the reset/overlay/scope flows still work unchanged.
