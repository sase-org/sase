---
create_time: 2026-06-26 12:51:36
status: done
prompt: sdd/prompts/202606/projects_admin_center_tab.md
bead_id: sase-5a
tier: epic
---
# Plan: Move Project Management into a "Projects" tab of the SASE Admin Center

## Goal

Retire the standalone **Project Management** modal and its `,p` leader keymap, and re-home all of its functionality as a
new **Projects** tab inside the **SASE Admin Center** (`ConfigCenterModal`, opened with `#`). The Projects tab sits
immediately to the **right of the Config tab**.

Hard requirements from the request:

- The `,p` keymap is removed.
- The panel is reachable via a new **Projects** tab, placed to the right of **Config**.
- **Zero loss of functionality** — every behavior of today's Project Management modal must be reproducible from the new
  tab.
- The result should be **intuitive, reliable, and beautiful**.

## Why this is straightforward (and low-risk)

The codebase already did this exact migration once: the **XPrompts** tab is a former standalone `XPromptBrowserModal`
that was moved into `XPromptBrowserPane` (a plain `Vertical` widget) hosted by `ConfigCenterModal`'s `ContentSwitcher`.
We follow that precedent step for step.

Crucially, today's Project Management logic is already cleanly split into reusable, screen-agnostic pieces:

- `src/sase/ace/tui/modals/project_management_actions.py` — `ProjectManagementActionsMixin`
  (lifecycle/activate/deactivate/delete/aliases/edit/force). It only uses Widget/App-level APIs (`self.app`,
  `self.notify`, `self.query_one`, `self.app.push_screen`, `self.app.suspend()`), so it works unchanged inside a pane.
- `src/sase/ace/tui/modals/project_management_rendering.py` — pure rendering/status helpers (column headers, row labels,
  state tabs, summary, detail, footer, confirm messages). No screen dependency.

Only the thin shell — `ProjectManagementModal` (the `ModalScreen` itself: `compose`, `load/filter/refresh`, screen-level
`BINDINGS`) — needs to be reworked into a pane.

The shared sub-modals it pushes (`ProjectAliasEditorModal`, `ConfirmActionModal`) are already independent `ModalScreen`s
pushed via `self.app.push_screen`, which works fine from a widget. They are **not** changed.

## Scope boundary (no Rust changes)

This is **presentation-only**: Textual widgets, layout, keybindings, and Python glue. All backend project-lifecycle
behavior stays behind the existing facades (`sase.core.project_lifecycle_facade.list_project_records`,
`sase.main.project_handler.{set_project_state_locked, set_project_aliases_locked, delete_project_locked, ProjectLifecycleBlockedError}`).
**No changes to `../sase-core` are required.** Implementers should not reimplement or relocate lifecycle logic.

---

## Design

### Tab identity and placement

In `src/sase/ace/tui/modals/config_center_modal.py`:

- `CenterTab = Literal["config", "projects", "plugins", "xprompts"]`
- `_TAB_ORDER = ("config", "projects", "plugins", "xprompts")` — Projects directly right of Config (so `]` from Config
  lands on Projects).
- `_TAB_LABELS`: insert `("projects", "Projects")` after `("config", "Config")`.
- `_TAB_COLORS`: add `"projects": "#FFAF5F"` — a warm amber accent, visually distinct from config green (`#00D7AF`),
  plugins purple (`#AF87FF`), and xprompts cyan (`#87D7FF`). Deliberately **not** gold (`#FFD700`), which the pane
  already uses to mean "inactive" project state.
- `#` still opens on the **Config** tab (unchanged default). Projects is reached with `]`/`[` or by clicking the tab,
  exactly like the other tabs.
- Update the module docstring to list four tabs and describe Projects.

### New widget: `ProjectsPane`

New file `src/sase/ace/tui/modals/projects_pane.py`:

```
class ProjectsPane(ProjectManagementActionsMixin, OptionListNavigationMixin, Vertical):
    _option_list_id = "projects-list"
```

- **Reuses the existing mixin and rendering helpers unchanged.** The pane re-homes the `compose`, record loading,
  filtering, option-refresh, summary/detail/footer-update, and selection helpers currently in `ProjectManagementModal`,
  re-prefixing element IDs from `project-management-*` to `projects-*` (`projects-list`, `projects-filter`,
  `projects-state-tabs`, `projects-summary`, `projects-columns`, `projects-detail-scroll`, `projects-detail`,
  `projects-hints`).
- **No outer `Container`.** Like `XPromptBrowserPane`, the pane _is_ the container and yields its children directly; the
  `ContentSwitcher` sizes it to 100%.
- **Constructor:** `ProjectsPane(projects_root: Path | None = None)` preserving the test-only `projects_root` override.
  `ConfigCenterModal.compose` yields `ProjectsPane(id="projects")`. (The pane lists _all_ projects, so it does not need
  the Admin Center's `project` name context that XPrompt uses.)
- **`focus_default()`** focuses the OptionList (browse-first), matching `ConfigPane` and `PluginsBrowserPane` and
  preserving today's modal UX (list focused on open; `/` jumps to the filter).
- **Preserve every keybinding** as pane-level bindings (priority where the modal used priority): `/`, `tab`/`shift+tab`
  (cycle state filter), `j`/`k`/`down`/`up`/`ctrl+n`/ `ctrl+p` (navigate), `m` (mark), `u` (unmark all), `e` (edit
  spec), `A` (aliases), `a` (activate), `d` (deactivate), `ctrl+d` (delete), `F` (force), `enter` (default action), `R`
  (reload), `ctrl+x` (toggle inactive). Closing is handled by the host modal's existing `escape`/`q` → close bindings,
  which bubble up from the pane (more reliable than the modal, which had no explicit close binding).

### Filter-input key forwarding (the one real subtlety)

When the filter `Input` has focus, printable keys are swallowed by `Input` before screen/pane bindings fire. The
XPrompts pane solves this with a custom `Input.on_key` that forwards `[`/`]` to the host's
`action_prev_center_tab`/`action_next_center_tab`. The Projects filter must do the same, **plus** forward
`tab`/`shift+tab` to the pane's `action_cycle_state_filter` / `action_cycle_state_filter_reverse` — because today those
are screen-level _priority_ bindings that fire even while the filter is focused, and we must preserve that behavior.

Implementation: a small `_ProjectsFilterInput(FilterInput)` subclass (mirroring `_BrowserFilterInput` in
`xprompt_browser_pane.py`) with an `on_key` that:

- forwards `left_square_bracket`/`right_square_bracket` to the host modal's tab actions;
- forwards `tab`/`shift+tab` to the owning pane's state-filter cycle actions.

### Styling

In `src/sase/ace/tui/styles.tcss`:

- Add `#projects-*` rules mirroring the current `#project-management-*` block, adapted for the pane context (the pane
  fills the switcher; no fixed-size outer container).
- Add `ProjectsPane` to the existing `ConfigCenterModal ConfigPane, ... PluginsBrowserPane, ... XPromptBrowserPane`
  `width: 100%; height: 100%` rule.
- The Projects pane footer becomes a single dim **hints** line (`projects-hints`), consistent with
  `plugins-hints`/`browser-hints`, and explicitly ends with `[ / ] switch tab   q close` so the tab teaches its own
  navigation (important now that there is no dedicated `,p` shortcut). The existing keybinding hint string from
  `footer_text()` is reused for the action portion.
- Remove the now-dead `ProjectManagementModal`/`#project-management-*` rules when the modal is deleted (Phase 2).
  **Keep** `ProjectAliasEditorModal` and `ConfirmActionModal` styles — still used by the pane.

### Quick access without `,p`

The command palette currently has a special-cased `projects` command that calls `open_project_management_panel`.
Re-point it to open the Admin Center **on the Projects tab** (`ConfigCenterModal(initial_tab="projects")`) via a small
new app action. Keep its discoverable label/aliases (e.g. "Open project management", aliases including "project
management", "projects"). This preserves a fast, searchable path to the panel for the muscle memory `,p` used to serve,
without reintroducing a leader key.

### Beauty / intuitiveness intent

- Visual language matches the Admin Center: the segmented `active / sibling / inactive / all` state tabs (already styled
  like the notification sub-tabs) act as the pane's header, harmonizing with the existing tab strip and divider rhythm;
  a redundant "Project Management" title is dropped since the Admin Center header + highlighted "Projects" tab already
  name the view.
- A distinct, warm tab accent (`#FFAF5F`) that complements the existing trio.
- Self-describing hints line including tab-switch/close so navigation is discoverable.
- Searchable command-palette fast path replaces the removed leader key.
- Reliability: identical action mixin + rendering helpers means behavior is preserved by construction; the only new code
  paths (compose/ID wiring + key forwarding) are covered by migrated and new tests.

---

## Phases

Four phases, each independently implementable and each ending with a green tree (`just install` then `just check`;
visual phase also `just test-visual`). Repo-relative paths only.

### Phase 1 — Build `ProjectsPane` and integrate it into the Admin Center (additive)

Make the new tab fully functional **without** removing anything yet, so the tree stays green and the old `,p` path keeps
working during cutover.

- Create `src/sase/ace/tui/modals/projects_pane.py` (`ProjectsPane`) reusing `ProjectManagementActionsMixin` and
  `project_management_rendering`; re-prefix IDs to `projects-*`; implement `compose`, `on_mount`,
  load/filter/refresh/detail/summary helpers (ported from the modal), `focus_default` (focus list), and the
  `_ProjectsFilterInput` forwarding described above.
- Register the tab in `config_center_modal.py`: `CenterTab`, `_TAB_ORDER`, `_TAB_LABELS`, `_TAB_COLORS`, yield
  `ProjectsPane(id="projects")` in `compose`, and update the docstring.
- Add `#projects-*` CSS and the `ProjectsPane` entry to the pane sizing rule in `styles.tcss`.
- Export `ProjectsPane` from `src/sase/ace/tui/modals/__init__.py`.
- Add a focused smoke test: open `ConfigCenterModal`, press `]` from Config, assert the Projects pane is the active tab
  and its list mounts.
- **Do not** touch the old modal, `,p` keymap, catalog, or help yet.

Exit criteria: `#` → `]` reaches a fully working Projects tab with all keybindings; old `,p` modal still works;
`just check` green.

### Phase 2 — Cutover: remove `,p` and the standalone modal, rewire entry points, migrate unit tests

- Delete `src/sase/ace/tui/modals/project_management_modal.py`. **Keep** `project_management_actions.py` and
  `project_management_rendering.py` (now owned by the pane).
- Remove the keymap and its wiring:
  - `src/sase/default_config.yml`: delete the `projects: "p"` leader entry.
  - `src/sase/ace/tui/keymaps/types.py`: delete `"projects"` from `LeaderModeKeymaps.keys` default dict.
  - `src/sase/ace/tui/actions/base.py`: delete `action_open_project_management_panel`; add a small `action`/helper that
    opens `ConfigCenterModal(initial_tab="projects")`.
  - `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`: delete the `projects` dispatch block.
  - `src/sase/ace/tui/commands/catalog.py`: re-point the `projects` command to the new "open Admin Center on Projects
    tab" action; keep label/aliases.
  - `src/sase/ace/tui/modals/__init__.py`: remove `ProjectManagementModal` import/export.
- Remove the dead `ProjectManagementModal`/`#project-management-*` CSS from `styles.tcss` (retain alias-editor /
  confirm-modal styles).
- Migrate the existing unit tests to drive `ProjectsPane`:
  - `tests/ace/tui/modals/project_management_modal_test_helpers.py` (rename/retarget the test app to mount the pane),
  - `tests/ace/tui/modals/test_project_management_modal_{states,marks,delete,edit,filtering}.py` (drive `ProjectsPane`;
    update monkeypatch targets from `...modals.project_management_modal.*` to `...modals.projects_pane.*`).
  - Add interaction tests for entering/leaving the Projects tab via `[`/`]`, and for filter-input key forwarding
    (`[`/`]` and `tab`/`shift+tab` while the filter is focused).
  - `tests/test_keymaps_defaults.py`: drop the `projects == "p"` assertion (and assert `"projects"` is no longer a
    leader key); keep the `temporary_llm_override` assertion.
  - Update any command-palette catalog tests that referenced the old `projects` executor.

Exit criteria: `,p` is gone; modal deleted; all entry points re-pointed; full unit suite migrated and green via
`just check`.

### Phase 3 — Help and documentation sync

Honor the strict help/footer/keymap-doc conventions in `src/sase/ace/AGENTS.md`.

- Help modal binding files: remove the `,p` "Project management" leader entry and update the `open_config_center` (`#`)
  description to reflect the new four-tab Admin Center (incl. Projects) in:
  - `src/sase/ace/tui/modals/help_modal/agents_bindings.py`
  - `src/sase/ace/tui/modals/help_modal/axe_bindings.py`
  - `src/sase/ace/tui/modals/help_modal/changespecs_bindings.py` Keep within the file's existing formatting/box-width
    conventions; verify against any help-modal width/snapshot tests.
- Grep the repo for residual references to the old shortcut and panel name (`,p`, `projects: "p"`, "Project Management"
  panel, `open_project_management_panel`) across docs/markdown, generated skills, and config; update or regenerate as
  needed. Note: per `memory/build_and_run.md`, pure markdown/research-doc edits don't require `just check`, but any
  code/skill-generation changes do.

Exit criteria: help and docs reflect the new world; help-modal tests and `just check` green.

### Phase 4 — Visual snapshots and final polish

- Add Projects-tab PNG snapshot tests to `tests/ace/tui/visual/test_ace_png_snapshots_config_center.py` using the
  existing `_open_modal(page, "projects")` harness, with `list_project_records` stubbed for deterministic data. Cover:
  default list, a marked set, inactive-rows-visible, and the detail pane populated. Generate goldens with
  `--sase-update-visual-snapshots`.
- Visual QA for beauty: column alignment with the shared width constants, state-tab and accent colors, divider/spacing
  rhythm matching the other tabs, hints-line legibility.
- Final `just check` and `just test-visual`.

Exit criteria: deterministic Projects-tab snapshots committed; visuals polished; full checks green.

---

## Functionality parity checklist (must all survive)

Navigation/filter: `/` focus filter; `tab`/`shift+tab` cycle state filter (active→sibling→inactive→all);
`j`/`k`/`down`/`up`/`ctrl+n`/`ctrl+p` move; text filter across name/aliases/state/workspace/warnings; `ctrl+x` toggle
inactive visibility. Marking: `m` toggle mark (auto-advance), `u` clear all marks, mark persistence across filters,
stale-mark pruning on reload, marked-set targeting for bulk ops. Lifecycle: `a` activate, `d` deactivate, `enter`
default (activate if inactive), `F` force after a blocked change, blocked/skipped/failed reporting, lifecycle-changed
cascade refresh of changespecs/agents/axe/current tab. Editing: `e` open ProjectSpec in `$EDITOR` (with edit-lock + TUI
suspend), `A` alias editor modal (with clear-confirm), normalization/dedup/sort. Deletion: `ctrl+d` single and bulk
delete with confirmation modal, system/`home` protection, deleted/blocked/failed reporting. Misc: `R` reload (preserving
selection), summary counts + marked + search + inactive status line, detail pane content, confirm/force/bulk messages,
toast notifications.

## Risks and mitigations

- **Filter-input swallows `[`/`]`/`tab`**: mitigated by the `_ProjectsFilterInput` forwarding (proven pattern from
  `_BrowserFilterInput`); covered by Phase 2 tests.
- **ID collisions / stale CSS**: re-prefix all IDs to `projects-*` and remove dead `#project-management-*` CSS in the
  same phase the modal is deleted.
- **Monkeypatch targets move** when logic imports relocate to `projects_pane.py`: handled explicitly in Phase 2 test
  migration.
- **Help-modal box-width rules** (`src/sase/ace/AGENTS.md`): Phase 3 verifies against help-modal width/snapshot tests.
- **Coexistence window** (Phase 1 keeps both modal and pane): acceptable, short-lived, and keeps the tree green; the
  shared mixin/rendering means no logic is duplicated, only the thin shell.
