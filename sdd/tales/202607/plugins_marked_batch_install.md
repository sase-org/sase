---
create_time: 2026-07-07 00:04:28
status: done
prompt: sdd/prompts/202607/plugins_marked_batch_install.md
---
# Plan: Mark-and-Batch-Install Plugins in the Admin Center Updates Tab

## Context

The **Updates** tab of the SASE Admin Center (the `PluginsBrowserPane`, an `OptionList` of plugin rows under
`src/sase/ace/tui/modals/plugins_browser_*.py`) currently lets the user install the **single highlighted** plugin with
the `i` keymap. There is no way to queue up several plugins and install them together — you must install, wait for the
resulting ACE restart, reopen the tab, and repeat.

This plan adds a **marking** workflow: press `I` to mark the highlighted plugin (toggle), mark as many as you like, then
press `i` once to install the whole marked set in a single operation. When nothing is marked, `i` keeps its current
single-plugin behavior, so the change is fully backward compatible.

The design deliberately mirrors the app's four existing "mark → batch action" conventions (ChangeSpecs, Agents,
Notifications, agent-cleanup Tags) so it feels native to anyone who has used marking elsewhere in SASE.

### Key constraints discovered

1. **The Updates tab uses hardcoded Textual `BINDINGS` on the pane**, not the config-driven `ace.keymaps.app` system. So
   this feature does **not** touch `default_config.yml`, the keymap loader, or the global help modal. New keys are added
   directly to the pane's `BINDINGS` list and dispatched to `action_*` methods.
2. **`m` and `u` are already bound** in this tab (`switch_mode`, `update_sase`). That is why the app-wide "`m` = mark"
   convention can't be reused here — and why the requested `I` (mark-for-**I**nstall) / `i` (**i**nstall) pairing is the
   natural, mnemonic fit. The tab already contains lowercase/uppercase sibling pairs (`u`/`U`, `g`/`G`), so `i`/`I`
   follows an established local pattern.
3. **A successful install triggers a full ACE restart** (`_handle_code_update_completion`). A naive "loop and install
   each" approach would restart after the first plugin and never reach the rest. Therefore batch install **must**
   resolve all marked plugins into a **single `uv` operation** that injects them together, producing exactly **one**
   restart.
4. **Plugin install is pure Python** (`src/sase/plugins/operations.py` → `uv_tool` → `uv` subprocess); it does **not**
   cross the Rust `sase_core` boundary. Marking is presentation-only Textual state. So all work is Python-side in this
   repo, with the reusable batch-planning logic living in the plugins backend (not the widget).

## Goal / Desired Behavior

- `I` (Shift+I) **toggles a mark** on the currently highlighted plugin. Only _installable_ plugins (not already
  installed, and sase is a `uv tool` install) can be marked.
- `i` **installs**:
  - If **one or more plugins are marked** → install the entire marked set as one atomic operation, behind a single
    confirmation preview, resulting in one ACE restart.
  - If **nothing is marked** → install the highlighted plugin (today's exact behavior).
- Marked plugins are **visually obvious** at a glance, the **count** is surfaced, and the **confirmation modal**
  enumerates exactly what will be installed before anything runs.
- Marks are **self-cleaning**: cleared after the batch install completes, and pruned whenever the plugin list reloads or
  a marked plugin's state changes.

## Design

### 1. Keymaps (added to `PluginsBrowserPane.BINDINGS`)

| Key      | Action                | Behavior                                                                                                                                                                                                   |
| -------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `I`      | `toggle_install_mark` | Toggle the mark on the highlighted installable plugin, then auto-advance the cursor to the next installable row (rapid marking). No-op (with a gentle toast) on a non-installable row.                     |
| `space`  | `toggle_install_mark` | _(Optional, recommended)_ Ergonomic alias — `space` is the universal "toggle checkbox" gesture and is unused in this tab. Mirrors the agent-cleanup Tag modal, which binds both `space` and `m` to toggle. |
| `i`      | `install`             | **Modified**: install the marked set if any exist, else the highlighted plugin.                                                                                                                            |
| `escape` | _(clear-then-close)_  | _(Optional, recommended)_ When marks exist, the first `esc` clears all marks; with no marks it closes the tab as it does today. Gives a one-key "never mind" without consuming a visible letter.           |

All three new behaviors are additive; `i` with an empty mark set is byte-for-byte the current flow.

### 2. Mark state

Add a single field to the pane, keyed on the stable plugin identity already used as the `OptionList` option id
(`entry.name`):

```python
self._marked_install: set[str] = set()   # plugin names queued for install
```

This matches the established pattern (`_marked_notification_ids`, `_marked_tags`, `_marked_projects`, ChangeSpec
`marked_indices`). A plain set is sufficient — unlike the agents feature, install order does not matter (uv resolves the
combined requirement set), so no parallel ordered list is needed.

### 3. Visual design (the "beautiful" part)

Reuse the app's **canonical marking treatment** so it reads as the same idea users already know from the ChangeSpecs and
Agents lists:

- **Row indicator**: a reserved left-most mark column rendered in `_row_text` (`plugins_browser_rendering.py`). Marked →
  `[✓] ` in `bold #00D700` (the exact style used by `_changespec_list_helpers.py` and `_agent_list_render_agent.py`);
  unmarked → equal-width blanks so columns stay perfectly aligned. The mark sits to the _left_ of the existing
  installed/available status glyph, so it never competes with the green "installed" glyph (marks only ever appear on
  not-installed rows anyway).
- **Count surfacing**: show `N marked` in `bold #00D700` in the hints/status line (`plugins_browser_status.py`),
  matching the `[N marked]` info-panel convention elsewhere.
- **Efficient repaint**: on each toggle, patch only the affected row via
  `OptionList.replace_option_prompt_at_index(idx, new_prompt)` (guarded against spurious highlight events, exactly as
  `changespec_list.py` does) rather than rebuilding the list.

### 4. Hints line (`plugins_browser_status._hints`)

Extend `_hints()` and add matching `_can_*` predicates, following the existing gated-hint pattern:

- Show `I mark` (or `I/␣ mark`) when the highlighted row is installable (`_can_mark_highlighted`, same predicate as
  `_can_install_highlighted`).
- When `self._marked_install` is non-empty:
  - Change `i install` → `i install (N)` to signal the batch.
  - Append `N marked` and (if `esc` clear is adopted) `esc clear`.

The global `?` help modal does not cover the Updates tab, so no help-modal changes are needed.

### 5. Batch install flow

Modify `action_install` (`plugins_browser_install.py`) to branch:

```
if self._marked_install (non-empty):
    -> _begin_batch_install_plan(sorted marked names)
else:
    -> existing _begin_install_plan(highlighted name)   # unchanged
```

The batch path reuses the existing worker → preview → confirm → tracked-task machinery, generalized from one plugin to
many:

1. **Plan (off-thread worker)**: call a new backend entry point `plan_install_many(names)` in
   `src/sase/plugins/operations.py`. It resolves each name to a `ResolvedSpec` (reusing the current per-plugin
   resolution), drops any that are `AlreadyInstalled` / `InstallNotFound` / non-uv-tool (collecting them as
   skipped-with-reason), and emits a single combined `InstallReady`-style plan whose `argv` injects **all** target
   plugins in one `uv` command. This generalizes exactly what single-plugin planning already does to keep other injected
   plugins intact — it just adds the full marked set to the desired requirement list instead of one.
2. **Confirm**: push a batch variant of `PluginActionConfirmModal` titled e.g. "Install N plugins", listing each plugin
   (name + source label: index / git / editable) and surfacing any skipped entries with their reason. This is the
   "reliable" guarantee — the user sees the exact set and the exact command before anything runs.
3. **Execute**: on confirm, submit **one** tracked background task
   (`self.app._submit_tracked_task("plugin-install", ...)`) that runs the single combined `uv` argv via
   `execute_install_many` (thin sibling of `execute_install`). One subprocess, one success, one ACE restart via the
   existing `_handle_code_update_completion`.
4. **Clear**: clear `self._marked_install` on successful submission/completion. If the user cancels the confirm modal,
   marks are preserved so they can adjust the set.

Placing `plan_install_many` / `execute_install_many` in `src/sase/plugins/operations.py` (alongside the existing
single-plugin functions) keeps the TUI widget thin and makes the batch behavior reusable by any future frontend (e.g. a
`sase plugin install A B C` CLI), consistent with the layering already used for single install.

### 6. Reliability & edge cases

- **Only installable rows can be marked.** Marking is gated by the same predicate as install, so there is never a
  "marked but un-installable" limbo. `I` on a header row, installed plugin, or when sase isn't a uv-tool install is a
  no-op with a short toast.
- **Stale-mark pruning.** When the catalog reloads (refresh, offline toggle, post-install), drop any marked name that is
  gone or now installed — mirroring `_prune_stale_marked_agents`. This keeps the count honest.
- **Concurrency guards.** Respect the existing `self._loading` / `self._plan_worker` guards: block marking and install
  while a plan/install is in flight (same early-returns `action_install` already uses).
- **Precedence.** If marks exist, `i` installs the marked set even when the highlighted row is a different (or
  already-installed) plugin. Marks always win over the cursor.
- **Batch of one** behaves identically to a single install (consistent, no special-casing).
- **Partial planning failures** (a marked plugin can't be resolved) are surfaced in the confirm modal's skipped list
  rather than silently dropped; if _nothing_ installable remains, abort with an explanatory toast and leave marks
  intact.

## Scope / Files

Python-only, all within this repo (no `sase_core` / Rust changes; no `default_config.yml` changes):

- `src/sase/ace/tui/modals/plugins_browser_pane.py` — new `BINDINGS` entries (`I`, optional `space`, optional `escape`
  handling); `_marked_install` state init.
- `src/sase/ace/tui/modals/plugins_browser_install.py` — `action_toggle_install_mark`; branch `action_install`;
  `_begin_batch_install_plan`, `_open_batch_install_modal`, `_submit_batch_install_task`, `_on_batch_install_*`
  handlers.
- `src/sase/ace/tui/modals/plugins_browser_rendering.py` — mark glyph in `_row_text`; single-row repaint + cursor
  auto-advance on toggle; stale-mark pruning on reload.
- `src/sase/ace/tui/modals/plugins_browser_status.py` — `_hints()` additions, `_can_mark_highlighted`, marked-count
  display.
- `src/sase/ace/tui/modals/plugin_action_confirm_modal.py` — batch/multi-plugin variant (title + enumerated plugin
  list + skipped section).
- `src/sase/plugins/operations.py` — `plan_install_many(names)` and `execute_install_many` (combined-argv
  planning/execution), generalizing the existing single-plugin logic.

## Testing

- Follow `tests/ace/tui/test_plugins_browser_pane_install.py`, which drives actions directly and asserts on
  `pane._hints()`:
  - `action_toggle_install_mark` adds/removes the name in `_marked_install`, is a no-op on non-installable rows,
    auto-advances the cursor, and updates the row prompt + hints.
  - With marks set, `action_install` takes the batch path: the confirm modal lists all marked plugins, the combined `uv`
    argv contains every marked plugin, and marks clear on completion. With no marks, it still takes the single-plugin
    path.
  - Stale-mark pruning after a simulated reload; precedence of marks over the highlighted row.
- Unit tests for `plan_install_many` / `execute_install_many` in the plugins-operations test suite (combined argv
  correctness, skip-and-report of already-installed/not-found, empty-installable abort).
- **Visual snapshots**: marking changes row rendering. If the Updates tab is covered by the ACE PNG snapshot suite
  (`tests/ace/tui/visual/snapshots/png/`), add/refresh a golden showing marked rows and the count, using
  `--sase-update-visual-snapshots` only to accept the intentional change.

## Validation

- `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy + tests).
- Targeted: `pytest tests/ace/tui/test_plugins_browser_pane_install.py` and the plugins operations tests.
- `just test-visual` if a Updates-tab visual golden is added/changed.

## Open decisions (for approval)

1. **`space` as a mark alias** — recommended (ergonomic, precedented). Drop if you want `I` to be the only mark key.
2. **`esc` clears marks before closing** — recommended (elegant one-key "never mind", no extra visible key). If you'd
   rather not overload `esc`, the alternative is a dedicated visible clear key; note `u` is taken here, so `c` (clear)
   would be the fallback. Without either, unmarking is via toggling `I` again plus auto-clear after install.
3. **Mark glyph** — `[✓] ` bold-green to match the app-wide marking convention. Alternative is the always-visible
   `[ ]`/`[x]` checkbox gutter used by the Tag modal.

## Acceptance Criteria

- Pressing `I` on an installable plugin marks it (visible `[✓]`), advances the cursor, and updates the marked count;
  pressing `I` again unmarks it.
- With ≥1 plugin marked, `i` opens a confirmation listing every marked plugin and, on confirm, installs them all via a
  single `uv` operation and a single ACE restart.
- With nothing marked, `i` behaves exactly as before (single highlighted install).
- Marks auto-clear after install and are pruned when the list reloads; non-installable rows cannot be marked.
- `just check` passes; no changes to `default_config.yml` or the Rust core are required.
