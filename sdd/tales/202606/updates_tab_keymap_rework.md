---
create_time: 2026-06-29 11:38:39
status: done
prompt: sdd/prompts/202606/updates_tab_keymap_rework.md
---
# Plan: Rework the Updates-tab update keymaps (`S` / `u` / `U`)

## Summary

On the **Updates** tab of the **SASE Admin Center** (the `ConfigCenterModal` "updates" pane), three keymaps currently
trigger updates:

| Key | Action method        | Today's behavior                                                                   |
| --- | -------------------- | ---------------------------------------------------------------------------------- |
| `u` | `action_update`      | Update the **highlighted plugin** only.                                            |
| `U` | `action_update_all`  | Update **every installed plugin**.                                                 |
| `S` | `action_update_sase` | Run the **comprehensive `sase update`** (host `sase` + `sase-core` + all plugins). |

We want to collapse this to two keymaps with clearer roles:

| Key | New behavior                                                                                                                                                                      |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `u` | Run the **comprehensive update** (everything that needs updating: `sase`, `sase-core`, plugins). If **nothing** needs updating, surface an **error toast** instead of proceeding. |
| `U` | Update **only the currently selected plugin**, and only be **available when that plugin needs updating**.                                                                         |
| `S` | **Removed.**                                                                                                                                                                      |

The "update every installed plugin" action (`action_update_all`) is **dropped** — it is subsumed by the comprehensive
`u` action (which already upgrades all plugins along with the host and core).

## Background / where this lives

All three bindings are **widget-local Textual `BINDINGS`** on the `PluginsBrowserPane` (the Updates tab body), declared
in `src/sase/ace/tui/modals/plugins_browser_pane.py`:

```python
("u", "update", "Update"),
("U", "update_all", "Update all"),
("S", "update_sase", "Sase update"),
```

These are **not** config-driven keymaps — they do **not** appear in `src/sase/default_config.yml`. (The `u` / `U` / `S`
entries in `default_config.yml` are unrelated app-level actions: `clear_marks`, `toggle_agent_unread`,
`bulk_change_status`.) So `default_config.yml` does **not** change as part of this work.

The action methods come from mixins inherited by `PluginsBrowserPane`:

- `action_update` and `action_update_all` → `PluginUpdateActionsMixin`
  (`src/sase/ace/tui/modals/plugins_browser_update.py`).
- `action_update_sase` → `SaseUpdateActionsMixin` (`src/sase/ace/tui/modals/plugins_browser_sase_update.py`).

The on-screen key hints are rendered in a custom `Static` (`id="plugins-hints"`), built by `_hints()` in
`src/sase/ace/tui/modals/plugins_browser_status.py`. There is **no Textual `Footer`** in the pane or in
`ConfigCenterModal`, so `_hints()` is the only surface that advertises these keys; the main TUI footer / `?` help popup
do not document these modal-internal keymaps (verify with a grep — see "Docs & config").

Two facts drive the design:

- **"A plugin needs updating"** is already modeled by `PluginCatalogEntry.update_available`
  (`src/sase/plugins/catalog.py`), which handles both index-installed and editable/dev plugins. It already drives the
  `↑` emphasis glyph in `_hints()` and the row rendering.
- **The comprehensive update has two code paths** inside `SaseUpdateActionsMixin`:
  - **Dev / editable install** (the common case in a dev workspace): planned off-thread via
    `make_sase_dev_update_preview`. "Nothing to update" is known **at plan time** — `dev_update_blocking_reason(plan)`
    returns a message when `plan.actionable_roots` is empty (`"No editable checkout updates are available."`). It is
    currently shown as a **warning** toast in `_on_sase_update_preview`, before any modal opens.
  - **Managed / PyPI install** (`preview.plan is None`): opens a confirm modal that runs `uv tool upgrade sase`.
    "Nothing to update" is only known **after** the run (`UpdateSummary.changed` is false → `"Already up to date."`),
    surfaced today as a success/info toast in `_handle_code_update_completion`. There is **no cheap offline pre-check**
    for this path (resolution against the index is itself the check), so the error toast for managed installs
    necessarily appears post-run. See "Open questions" for an optional dry-run enhancement.

## Goals

1. Remove the `S` keymap and its action wiring.
2. Make `u` run the comprehensive update, and emit an **error toast** when nothing needs updating (instead of
   silently/successfully reporting "already up to date").
3. Make `U` update the **selected** plugin, and only be **available** (hint shown + action effective) when the selected
   plugin's `update_available` is true.
4. Drop the now-redundant "update all plugins" action and its dead helpers/tests.

## Non-goals

- No change to the actual update execution logic (uv/dev-update planning, confirm modals, restart-after-update behavior)
  beyond toast severity/wording for the no-op case.
- No change to `sase update` CLI behavior or to the shared `plan_update` / `sase.plugins.operations` source of truth.
- No change to `default_config.yml` (these are not config-driven keymaps).

## Design

### 1. Rewire the bindings (`plugins_browser_pane.py`)

Replace the three update bindings with two. Keep the existing **method names** (they describe the behavior accurately —
`action_update_sase` = comprehensive, `action_update` = single plugin); only the **key → action** mapping and the
binding descriptions change:

```python
("u", "update_sase", "Update"),        # comprehensive: sase + core + plugins
("U", "update", "Update plugin"),       # selected plugin only
# ("S", ...) removed
# ("U", "update_all", ...) removed
```

Rationale for not renaming methods: it minimizes churn/risk and keeps method names tied to _what they do_ rather than
_which key invokes them_. (If the implementer prefers self-documenting names, an optional rename — e.g.
`action_update_sase` → `action_update_all_targets` and `action_update` → `action_update_selected` — can be done, but
then all tests and any binding references must be updated in lockstep. Default to **not** renaming.)

### 2. `u` → comprehensive update with an error toast when nothing to update

The comprehensive action stays `action_update_sase` in `plugins_browser_sase_update.py`. Two small changes make "nothing
to update" an error:

- **Dev/editable path (pre-confirmation):** in `_on_sase_update_preview`, change the `dev_update_blocking_reason(...)`
  branch from `severity="warning"` to `severity="error"`. This makes the "no editable checkout updates are available"
  case an error toast, raised at plan time without opening a modal. (This branch also covers the "reconcile step
  unavailable" blocker, which is likewise a legitimate error — acceptable.)

- **Managed/PyPI path (post-run):** in `_handle_code_update_completion`, the success-but-no-change branch (today
  `self._notify(completion.message)` → `"Already up to date."`) becomes an **error** toast. Prefer a clearer message
  such as `"Nothing to update — sase, core, and plugins are current."` emitted with `severity="error"`, rather than
  reusing the "Already up to date." success string. The refresh/`_start_load` that follows should remain.

Update the `action_update_sase` docstring to note it is the `u` keymap and describe the error-on-nothing-to-update
contract.

> Note: For dev installs (the common dev-workspace case) the error appears immediately at plan time with no modal. For
> managed installs the error appears after confirm + run, because uv resolution is the only available "is anything
> updatable" check. This asymmetry should be called out in the implementation and is acceptable; see "Open questions"
> for an optional managed-path pre-check.

### 3. `U` → update selected plugin, only when it needs updating

The selected-plugin action stays `action_update` in `plugins_browser_update.py`, now bound to `U`. Two changes:

- **Availability gate (hint):** tighten `_can_update_highlighted()` in `plugins_browser_status.py` to require
  `entry.update_available` (in addition to "installed and a uv-tool install"). This automatically hides the `U` hint
  when the selected plugin is up to date or not installed.

- **Action guard:** in `action_update`, after the existing `NotUvToolInstall` warning, return **silently** when the
  selected entry is not installed or `not entry.update_available` (it is "not available", consistent with the hidden
  hint). Keep the `NotUvToolInstall` warning toast (a distinct, useful condition). The dev-vs-managed branch
  (`entry_uses_dev_update`) and the rest of the flow are unchanged.

### 4. Update the hints (`_hints()` in `plugins_browser_status.py`)

Rebuild the update-related hint parts:

- Replace the old single-plugin hint (`"u upd ↑"`/`"u upd"`, gated on the old `_can_update_highlighted`) and the
  `"S sase"` part with:
  - `"u update"` whenever `_can_update_sase()` (comprehensive; always offered on a uv-tool install — it self-reports
    when nothing needs updating).
  - `"U upd ↑"` (selected plugin) only when the tightened `_can_update_highlighted()` is true. Since that now implies
    `update_available`, the `↑` emphasis is always appropriate here.
- Remove the `"U all"` part and delete the now-unused `_can_update_all()` helper.

Exact label strings are adjustable; keep `u`/`U` distinguishable in the hint line.

### 5. Remove the dropped "update all" path

- Delete `action_update_all` from `PluginUpdateActionsMixin` (`plugins_browser_update.py`).
- Delete `_can_update_all()` from `plugins_browser_status.py` (only used by the removed hint).
- Remove the `catalog_all_installed_plugins_are_editable` import + call site in `plugins_browser_update.py`. Its
  definition + `__all__` export live in `plugins_browser_dev_update.py`; grep for remaining callers and remove the
  definition (and any dedicated test) if none remain.
- The following branches become unreachable from the TUI once `action_update_all` is gone (the TUI will only ever plan
  with `all_plugins=False`). Remove them as a clearly-scoped dead-code cleanup, verifying each with a grep first:
  - `no_plugins_message()` and its `_no_plugins_message` aliases (in `plugins_browser_update.py` and
    `plugins_browser_pane.py`), plus the `NoPlugins` branch in `_on_update_preview`.
  - The `plan.all_plugins` branches in `update_subject`, `_open_update_modal` ("Update all plugins" title/intro), and
    `_submit_update_task` ("all plugins" label / `plugin-update:all` dedup).
  - Leave the shared `plan_update` / `UpdateReady.all_plugins` machinery in `sase.plugins.operations` untouched (still
    used by the CLI).

  If the implementer judges the dead-branch removal too broad for one change, it may be split into a follow-up; the
  binding/behavior changes above stand on their own. Default to doing the cleanup in this change so no code references a
  removed feature.

## Files to change

- `src/sase/ace/tui/modals/plugins_browser_pane.py` — rewire `BINDINGS`; drop the
  `no_plugins_message`/`_no_plugins_message` import+alias if removed.
- `src/sase/ace/tui/modals/plugins_browser_sase_update.py` — error severity for the dev "nothing to update" blocker;
  error toast + clearer message for the managed no-op in `_handle_code_update_completion`; docstring update for
  `action_update_sase` (now `u`).
- `src/sase/ace/tui/modals/plugins_browser_update.py` — add the `update_available` guard to `action_update` (now `U`);
  delete `action_update_all` and its now-dead helpers/branches; docstring update.
- `src/sase/ace/tui/modals/plugins_browser_status.py` — tighten `_can_update_highlighted()`; rewrite the update hints;
  delete `_can_update_all()`.
- `src/sase/ace/tui/modals/plugins_browser_dev_update.py` — remove `catalog_all_installed_plugins_are_editable`
  (definition + `__all__`) if unused after the above.

## Tests

Update `tests/ace/tui/test_plugins_browser_pane_update.py`:

- **Hints** (`test_plugins_pane_update_hint_gated_on_installed` and the related assertions): rewrite the expectations —
  `"u update"` always present on a uv-tool install; `"U upd ↑"` present only when the highlighted entry has
  `update_available=True`, absent otherwise; `"U all"` and `"S sase"` no longer present. (Search the file for `"u upd"`,
  `"U all"`, `"S sase"` and update each.)
- **Selected-plugin update (`U` → `action_update`)**: ensure entries used by the "update proceeds" tests have
  `update_available=True`. Add a test that `action_update` is a **no-op (no toast, no worker)** when the selected plugin
  is up to date (`update_available=False`). Adjust `test_plugins_pane_update_not_installed_toasts` to the new
  silent-on-unavailable behavior (the `U` hint is hidden for not-installed/up-to-date).
- **Comprehensive update (`u` → `action_update_sase`)**: the existing `test_updates_pane_sase_update_*` tests keep
  exercising `action_update_sase`. Update the **no-op** case(s) (e.g. `test_updates_pane_sase_update_noop_*` and the dev
  "skipped reason" case) to assert an **error**-severity toast instead of success/warning.
- **Remove** `action_update_all` tests: `test_plugins_pane_update_all_no_plugins_toasts`,
  `test_plugins_pane_update_all_executes`, and the `action_update_all()` call inside
  `test_plugins_pane_update_disabled_when_not_uv_tool` (keep the `action_update` half).

Visual PNG snapshots (`tests/ace/tui/visual/`):

- Delete `test_config_center_plugins_update_all_preview_png_snapshot` and its golden
  `tests/ace/tui/visual/snapshots/png/config_center_plugins_update_all_preview_120x40.png`.
- Regenerate the snapshots whose hint line changed (`config_center_plugins_update_preview_120x40.png`,
  `config_center_plugins_core_update_available_120x40.png`, `config_center_plugins_dev_update_available_120x40.png`) via
  `just test-visual --sase-update-visual-snapshots` once the new hints are in, and confirm the diffs are intentional
  (only the hint text / no `U all`).

## Docs & config

- **`default_config.yml`**: no change (these keymaps are Textual `BINDINGS`, not config-driven). Call this out
  explicitly so review doesn't flag the keymap-config gotcha.
- **`?` help popup / footer**: per `src/sase/ace/AGENTS.md`, options changes must keep the help popup in sync. These are
  `ConfigCenterModal`-internal keymaps and appear unlikely to be in the main help/footer, but grep the help-modal source
  and `src/sase/ace/tui/widgets/keybinding_footer.py` for `update_sase` / `update_all` / "Sase update" / "Update all"
  and update if any references exist.
- Update the stale plan note in `sase_plan_post_update_version_toast.md` only if it is a living doc; otherwise leave it.

## Risks & validation

- **Risk:** dead-branch removal touches functions still used by the live single-plugin path (`update_subject`,
  `_open_update_modal`, `_submit_update_task`). Mitigation: the removed branches are gated on `plan.all_plugins`, which
  the TUI no longer produces; the single-plugin path is well covered by existing tests. Verify each removal with grep.
- **Risk:** managed-install users see the "nothing to update" error only after confirming + running. Accepted
  (documented above); optional pre-check noted below.
- **Validation:** run `just install` then `just check` (lint + mypy + targeted pytest for
  `tests/ace/tui/test_plugins_browser_pane_update.py`) and `just test-visual` for the affected snapshots. Manually
  exercise the Updates tab: `u` with and without pending updates (expect run vs error toast); `U` on an updatable vs
  up-to-date selected plugin (expect hint shown + run vs hidden + no-op); confirm `S` no longer does anything.

## Open questions

1. **Managed-path pre-check (optional):** to make the `u` error toast fire _before_ the confirm modal on managed/PyPI
   installs, the off-thread preview could run a `uv tool upgrade sase --dry-run`-style resolution and route an empty
   result to the error toast. This needs verification of uv's dry-run/resolution support and adds network latency; left
   out of the core plan. Worth doing only if managed installs are a priority.
2. **`U` no-op feedback:** the plan makes `U` a _silent_ no-op when the selected plugin is up to date (consistent with
   "not available" + hidden hint). If you'd rather give feedback, it could instead emit a small info toast ("Selected
   plugin is up to date"). Confirm preference.
3. **Method renames:** default is to keep `action_update_sase` / `action_update` names. Confirm whether you want them
   renamed for self-documentation (larger, lock-step test churn).
