---
create_time: 2026-06-27 08:51:12
status: done
prompt: sdd/prompts/202606/operations_tab.md
---
# Plan: Merge Admin Center "Tasks" + "Logs" into a single "Operations" tab

## Goal

The **SASE Admin Center** (`ConfigCenterModal`) currently has six top-level tabs:
`Config · Logs · Projects · Tasks · Updates · XPrompts`. Two of them — **Tasks** and **Logs** — are sibling
"operational" surfaces that each take a full top-level tab slot.

Replace them with a single new top-level tab, **Operations**, that hosts two **sub-tabs**: **Tasks** (default) and
**Logs**. The Admin Center drops from six tabs to five.

Hard requirements:

1. Operations has two sub-tabs: Tasks and Logs.
2. **Zero functional regressions** — each sub-tab behaves exactly like the old top-level tab did (live task polling,
   kill/dismiss/edit/copy, log source browsing, refresh, all scroll keymaps, focus behavior, hints).
3. Operations is sorted correctly in the tab strip and the numeric (`1`–`N`) hotkeys are renumbered accordingly.
4. **Tasks** is the default sub-tab the first time Operations is opened, but the active sub-tab is **remembered for the
   rest of the TUI session** (until the user quits), exactly like the Admin Center already remembers its active
   top-level tab.
5. The result should be intuitive, reliable, and visually polished.

## Design overview

### Why this shape

The Admin Center already implements a clean, proven tab pattern: a centered clickable tab strip
(`_ConfigCenterTabStrip`) over a `ContentSwitcher`, with digit hotkeys, `[`/`]` cycling, an accent-colored caption, and
session memory of the active tab on the long-lived app object (`app._admin_center_tab`).

The **Projects** tab demonstrates the in-pane idiom we mirror for sub-tabs: a centered, segmented strip
(`state_tabs_text`) where the active segment is highlighted and inactive segments are dimmed, switched via `Tab` /
`Shift+Tab`.

We compose these two existing, battle-tested patterns: **Operations is a small ContentSwitcher-with-a-tab-strip nested
inside the Admin Center's outer ContentSwitcher.** This reuses the exact `TasksPane` and `LogsPane` widgets unchanged in
behavior, so functional parity is preserved by construction.

### New top-level tab list (alphabetical, as today)

The Admin Center tabs are ordered alphabetically by label (enforced by
`test_admin_center_tabs_are_alphabetical_by_label`). After the merge:

| #   | Tab        | Notes                                   |
| --- | ---------- | --------------------------------------- |
| 1   | Config     | unchanged                               |
| 2   | Operations | **new** — replaces Logs (2) + Tasks (4) |
| 3   | Projects   | was 3                                   |
| 4   | Updates    | was 5                                   |
| 5   | XPrompts   | was 6                                   |

Digit hotkeys `1`–`5` map to these; `6`–`9`/`0` become out-of-range no-ops (already handled generically by
`action_focus_center_tab` via `len(_TAB_ORDER)`). `[` / `]` cycling and click-to-select continue to work with the
shorter list automatically.

### The Operations pane (new `OperationsPane`)

A new `operations_pane.py` module defines `OperationsPane(Vertical)`:

```
        Tasks  │  Logs            ← centered sub-tab strip (clickable)
  ┌─────────────────────────────────────────────┐
  │  (inner ContentSwitcher: TasksPane | LogsPane)│  ← unchanged panes
  └─────────────────────────────────────────────┘
```

- Composes a clickable sub-tab strip (`_OperationsSubTabStrip`, a small `Static` modeled on `_ConfigCenterTabStrip` +
  the Projects `state_tabs_text` visual idiom) plus an inner `ContentSwitcher(id="operations-switcher")` containing
  `TasksPane(id="tasks")` and `LogsPane(id="logs")` — the same pane classes and the same widget ids used today, just
  nested one level deeper.
- Tracks `self._active_subtab` (`"tasks"` | `"logs"`) as the single source of truth; the strip, the inner switcher, and
  active-tab detection all read it.
- `focus_default()` delegates to the active sub-pane's `focus_default()` so the outer modal's existing focus flow keeps
  working when Operations is selected.
- Forwards `action_scroll_to_top` / `action_scroll_to_bottom` to the active sub-pane so the modal's global `g`/`G`
  fallback (`ConfigCenterModal.on_key`) keeps working when Operations is the active top-level pane.

### Sub-tab navigation (intuitive + discoverable)

- **`Tab` / `Shift+Tab`** toggle between Tasks and Logs. This mirrors the Projects tab's `Tab`/`Shift+Tab` segment
  cycling (the requested inspiration). Neither `TasksPane` nor `LogsPane` binds `Tab` today, and a binding placed on
  `OperationsPane` (an ancestor of the focused `OptionList`) resolves before Textual's default focus traversal — this is
  exactly how `ProjectsPane`'s `Tab` binding already works, so the precedent is proven.
- **Click** any segment in the sub-tab strip to jump to it (mirrors the main tab strip's clickable behavior).
- `[` / `]` continue to cycle **top-level** Admin Center tabs from inside Operations (they bubble to the modal screen,
  unchanged), so there is a clear two-level mental model: `[`/`]` for outer tabs, `Tab` for inner sub-tabs.
- Each sub-pane's existing hint line is extended with a short `Tab: Tasks/Logs` affordance so the navigation teaches
  itself.

### Session memory of the active sub-tab

Mirror the existing top-level-tab memory:

- Add `app._operations_subtab: str = "tasks"` alongside `app._admin_center_tab` in `_state_init.py`.
- `OperationsPane` resolves its starting sub-tab on mount: an explicit request (see fast paths below) wins; otherwise
  the remembered `app._operations_subtab`; otherwise `"tasks"`.
- Every sub-tab switch persists `app._operations_subtab`, so closing/reopening the Admin Center within the same session
  returns to the last sub-tab used — and a fresh session starts on Tasks.

### Reliability: correct "is this sub-pane active?" detection

The one subtle correctness risk. Both `TasksPane` and `LogsPane` currently ask
`getattr(self.screen, "_active_tab", None) == self.id`. This guards two things:

- `TasksPane._refresh_running_output` (1s live-output poll) early-returns when the tab is not active.
- Both panes call `option_list.focus()` only when their tab is active (must not steal focus while another tab/the main
  app is showing).

After nesting, the screen's `_active_tab` becomes `"operations"`, never `"tasks"`/`"logs"`, so this check must be
reworked or it would (a) freeze live task output and (b) risk focus theft. New rule: a sub-pane is active iff **the
Operations top-level tab is active AND it is the selected sub-tab**.

Implementation: `OperationsPane.is_subtab_active(pane)` returns
`screen._active_tab == "operations" and self._active_subtab == pane.id`. A tiny import-free helper
(`subtab_host(widget)` added next to the existing mixins in `modals/base.py`) walks up parents to find the host by
duck-typing (`hasattr(node, "is_subtab_active")`) — the same walk-up idiom the panes' inner `OptionList` subclasses
already use (`_TaskList._pane`, `_LogSourceList._pane`). Each pane's `_is_active_tab()` delegates to the host when
present and falls back to the legacy screen check otherwise (keeps the panes usable in isolation).

This keeps `TasksPane`/`LogsPane` essentially behavior-identical: their internal logic is untouched; only the single
`_is_active_tab()` predicate becomes hierarchy-aware, and live polling now correctly pauses on the Logs sub-tab and
resumes (with an immediate repaint via `focus_default`) when Tasks is reselected.

### Fast-path entry points keep working

The command-palette commands still open the right surface directly:

- `action_open_tasks_panel` → open Admin Center on **Operations**, sub-tab **Tasks**.
- `action_open_log_panel` → open Admin Center on **Operations**, sub-tab **Logs**.
- `action_open_projects_panel` → unchanged (Projects).

To carry the requested sub-tab, `ConfigCenterModal` gains an optional `initial_operations_subtab` argument that it
forwards to `OperationsPane`. An explicit fast-path request both selects that sub-tab and updates the remembered
`app._operations_subtab` (so a subsequent plain `#` reopen returns to it) — matching how the old
`open_log_panel`/`open_tasks_panel` set `app._admin_center_tab`.

### Visual polish

- The Operations sub-tab strip reuses the Tasks/Logs accent identities so the surfaces stay recognizable: **Tasks =
  green (`#5FD75F`)**, **Logs = gold (`#FFD700`)** (their current `_TAB_COLORS` values). Active segment is rendered as a
  bold reverse-highlight "pill" in its accent color; inactive is dim — consistent with both the main tab strip and the
  Projects state strip.
- The Operations **top-level** accent gets its own slot in `_TAB_COLORS` (proposed green `#5FD75F`, tying the tab to its
  default Tasks sub-tab) and a caption in `_TAB_DESCRIPTIONS`, e.g. _"Monitor background tasks and browse SASE logs."_
  These flow through the existing gradient/caption machinery with no special-casing.
- The strip sits one line above the inner content, centered, with the sub-panes' existing titles/headers below — a
  clear, uncluttered two-level hierarchy.

### Boundary / scope notes

- This is **presentation-only** TUI work (tab layout, widget composition, keybindings, styling). No shared
  domain/backend behavior changes, so **no `sase-core` changes are required** per the Rust-core boundary rule.
  `TaskQueue` and log-source backends are reused untouched.
- The Admin Center digit/`[`/`]`/`Tab` bindings are local widget `BINDINGS`, not user-configurable keymap-registry
  entries, so `default_config.yml` needs no changes (verify during implementation). The only registry-bound action,
  `open_config_center`, is unchanged.

## Files to change

### New

- `src/sase/ace/tui/modals/operations_pane.py` — `OperationsPane`, `_OperationsSubTabStrip`, sub-tab constants/colors,
  `is_subtab_active`, `focus_default`, scroll forwarding, `Tab`/`Shift+Tab` actions, click handling, session-memory
  persistence.

### Core wiring

- `src/sase/ace/tui/modals/config_center_modal.py`
  - `CenterTab` literal → `config | operations | projects | updates | xprompts`.
  - `_TAB_ORDER`, `_TAB_LABELS`, `_TAB_COLORS`, `_TAB_DESCRIPTIONS`: drop `logs`/`tasks`, add `operations` in
    alphabetical position.
  - `compose`: replace the `LogsPane`/`TasksPane` children with a single `OperationsPane(initial_subtab=…)`.
  - Add `initial_operations_subtab` constructor arg, forwarded to the pane.
  - Update the module docstring (six tabs → five; describe Operations sub-tabs).
- `src/sase/ace/tui/modals/base.py` — add the `subtab_host(widget)` walk-up helper.
- `src/sase/ace/tui/modals/tasks_pane.py` — make `_is_active_tab()` host-aware; extend the hint line with the
  `Tab: Tasks/Logs` affordance.
- `src/sase/ace/tui/modals/logs_pane.py` — same two changes.
- `src/sase/ace/tui/modals/__init__.py` — export `OperationsPane` if the package re-exports panes (match the existing
  pattern).
- `src/sase/ace/tui/actions/base.py` — `action_open_tasks_panel` / `action_open_log_panel` open Operations with the
  right sub-tab.
- `src/sase/ace/tui/actions/_state_init.py` — initialize `app._operations_subtab = "tasks"`.

### Styling

- `src/sase/ace/tui/styles.tcss` — add `OperationsPane` layout: size the pane to fill the switcher, style
  `#operations-subtabs` (centered, height 1, bottom margin) and `#operations-switcher` (`1fr`), and ensure nested
  `TasksPane`/`LogsPane` still fill their area. Existing `ConfigCenterModal TasksPane/LogsPane` descendant selectors
  keep matching.

### Help / discoverability (required by the ace AGENTS.md "keep help in sync" rule)

- `src/sase/ace/tui/modals/help_modal/agents_bindings.py`, `changespecs_bindings.py`, `axe_bindings.py` — "Admin Center:
  1-6 jumps to tab" → "1-5".
- `src/sase/ace/tui/commands/_app_metadata.py` — add an `"operations"` search alias to the `open_config_center` command
  (keep existing `tasks`/`logs` aliases so muscle-memory searches still land in the Admin Center).
- `src/sase/ace/tui/commands/catalog.py` — keep the keyless Tasks/Logs commands (they still resolve to the same app
  actions); refresh their docstrings to say the panel now lives under the Operations tab.

### Tests (update to the new model)

- `tests/ace/tui/test_config_center_tabs.py` — new tab order/labels (`1 Config`, `2 Operations`, `3 Projects`,
  `4 Updates`, `5 XPrompts`); digit-hotkey, out-of-range, and session-memory assertions retargeted to the new positions.
- `tests/ace/tui/test_log_panel_keymap.py` — `_TAB_ORDER`/alphabetical assertion; `open_log_panel`/`open_tasks_panel`
  now assert top tab `operations` + the expected sub-tab.
- `tests/ace/tui/test_tasks_pane.py`, `tests/ace/tui/test_logs_pane.py` — open via Operations (+ correct sub-tab);
  rework `test_brackets_switch_admin_center_tabs_not_log_sources` for the new neighbor layout (Operations ↔
  Config/Projects) while confirming the sub-tab is preserved.
- **New** `tests/ace/tui/test_operations_pane.py` — sub-tab default is Tasks; `Tab`/`Shift+Tab` and click switch
  sub-tabs; session memory persists across close/reopen; `is_subtab_active` is true only for the visible sub-pane on the
  active top tab (guards live-poll/focus correctness); fast-path actions land on the right sub-tab.
- `tests/ace/tui/visual/_ace_config_center_png_snapshot_helpers.py` — update `_open_tasks_modal`/`_open_logs_modal` (and
  `_open_modal`) to drive Operations
  - sub-tab.
- Visual snapshot suites: reframe `test_ace_png_snapshots_config_center_tasks.py` / `..._logs.py` as
  Operations(Tasks)/Operations(Logs).

### Visual goldens (intentional updates)

The header tab strip (6→5 tabs) is present in **every** config-center PNG golden, so all `config_center_*` goldens plus
the renamed Operations Tasks/Logs goldens regenerate. Run `just test-visual` to see diffs, confirm they match the
intended design, then accept with `--sase-update-visual-snapshots`. The diff artifacts under
`.pytest_cache/sase-visual/` will be inspected before accepting.

## Risks & mitigations

- **Live task polling stalls / focus theft** — the central correctness risk; mitigated by the hierarchy-aware
  `is_subtab_active` and covered by a dedicated test. Switching to Tasks triggers an immediate snapshot repaint via
  `focus_default`.
- **`Tab` not reaching the sub-tab switcher** — proven viable by the existing Projects `Tab` binding; an explicit test
  asserts it.
- **Large golden churn** — expected and intentional (shared header strip); the plan treats it as a deliberate, reviewed
  snapshot update, not an incidental break.

## Out of scope

- Renaming `ConfigCenterModal`/`config_center_modal.py` (internal name kept).
- Any change to task/log backends, log sources, or `sase-core`.
- Migrating a persisted legacy `"tasks"`/`"logs"` tab value (session memory is per-run and resets to `config`).

## Verification

- `just install` then `just check` (lint + mypy + fast tests).
- `just test-visual` and accept intended golden updates with `--sase-update-visual-snapshots`.
- Manual smoke in `sase ace`: `#` opens Operations on Tasks first time; `Tab` toggles to Logs and back; live task output
  keeps updating on the Tasks sub-tab; close/reopen returns to the last sub-tab; `1`–`5` jump to the right tabs;
  command-palette "logs"/"tasks" land on the right sub-tab.
