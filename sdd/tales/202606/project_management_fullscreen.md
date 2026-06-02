---
create_time: 2026-06-02 12:13:10
status: done
prompt: sdd/prompts/202606/project_management_fullscreen.md
---
# Plan: Beautiful Near-Full-Screen Project Management Panel

## Goal

Redesign the `sase ace` **Project Management** modal so it takes up almost the whole screen and looks beautiful. Today
it is a small, content-sized centered modal with a cramped vertical stack. We want a polished, full-screen "command
center" for project lifecycle management that uses the available space well, reads cleanly, and matches the visual
language of our other large modals.

This is a **presentation-only** change (Textual layout, CSS, keybindings stay, Rich rendering). Per
`memory/short/rust_core_backend_boundary.md`, all data already flows through the existing `list_project_records` facade
/ `ProjectRecordWire`. **No `sase-core` / Rust changes are required**, and no project lifecycle behavior changes.

## Current State (what exists today)

- **Modal**: `src/sase/ace/tui/modals/project_management_modal.py` — `ProjectManagementModal(ModalScreen)`.
  - `compose()` (lines 91–103): a single `Container#project-management-container` with a vertical stack of `Label`
    (title) → `Static` (summary) → `FilterInput` → `OptionList` → `Static` (detail) → `Static` (footer).
  - All lifecycle actions live in `ProjectManagementActionsMixin` (`project_management_actions.py`):
    activate/archive/close/delete/edit/mark/force/reload.
  - Navigation via `OptionListNavigationMixin` (j/k/arrows/ctrl-n,p), filter via `FilterInput`.
- **Rendering**: `src/sase/ace/tui/modals/project_management_rendering.py` — `record_label`, `summary_text`,
  `footer_text`, `detail_text`, `state_style` (active=green, archived=gold, closed=orange). Columns are hand-padded
  inside `record_label` (name `<24`, workspace truncated to 46).
- **CSS**: `src/sase/ace/tui/styles.tcss` lines 545–599. Container is
  `width: 96; max-width: 96%; height: auto; max-height: 88%` — i.e. **content-sized, not full screen**. List capped at
  `max-height: 18`, detail capped at `max-height: 10`.
- **Open**: leader-mode `p` → `action_open_project_management_panel` (`actions/base.py:144`) →
  `push_screen(ProjectManagementModal())`.
- **Tests**: behavior tests in `tests/ace/tui/modals/test_project_management_modal_*.py` (filtering, marks, states,
  edit, delete) plus `project_management_modal_test_helpers.py` (`make_project_record`, `ProjectManagementTestApp`).
  **No PNG visual snapshot tests exist for this modal yet.**

## Established conventions to match (from the rest of the TUI)

- Large modals use `align: center middle` with a container at `width: 95%; height: 90%`,
  `border: thick/double $primary`, `background: $surface`, `padding: 1 2` (e.g. `NotificationModal`
  styles.tcss:1748–1832, `MentorReviewModal`, `EpisodeExplorerModal`).
- Fill remaining space with `height: 1fr`; scrollable detail uses `VerticalScroll` + `scrollbar-gutter: stable`.
- Theme variables: `$primary` (outer border), `$secondary` (internal dividers), `$surface` (bg), `$text-muted` (hints),
  plus the existing state hex colors.
- Idiomatic list widget is `OptionList` (keep it — DataTable would force a risky rewrite of the
  marking/navigation/action machinery and tests).
- Visual tests: `tests/ace/tui/visual/` with `AcePage` + `ace_png_visual.assert_page_png(page, "<name>_WxH")`;
  fonts/colors pinned by `conftest.py`. Snapshots in `tests/ace/tui/visual/snapshots/png/`.

## Design — the new layout

A "k9s/lazygit-style" command center: a header band, a wide full-width table-like list that fills the screen, and a rich
detail pane beneath it. Full-width (not a narrow left/right split) because project rows are **column-dense** (name,
state, claims, launchable, warnings, workspace path) and read far better with aligned columns and a header row than when
squeezed into a 40%-width sidebar.

```
┌─ Project Management ──────────────────────────────────────────────── (double $primary) ─┐
│  ACTIVE   archived   closed   all          12 projects · 8 active · 3 archived · 1 closed │  ← title + state tabs + counts
│  search ▸ [ type to filter projects...                                                  ] │  ← FilterInput
│                                                                                           │
│  ┌─ Projects ──────────────────────────────────────────────────────────────────────┐    │
│  │     NAME                      STATE      CLAIMS  LAUNCH  WARN   WORKSPACE          │    │  ← column header (dim/bold)
│  │ [✓] sase                      active        2     yes           ~/work/sase        │    │
│  │     other_project             archived      0     no      2     ~/work/other       │    │  ← OptionList, height: 1fr
│  │     ...                                                                            │    │
│  └────────────────────────────────────────────────────────────────────────────────┘    │
│  ┌─ Details ───────────────────────────────────────────────────────────────────────┐    │
│  │ sase   ● active (explicit)                                                        │    │  ← detail pane, fixed height
│  │ Project file: ...   Workspace: ...   Active claims: 2   Launchable: yes            │    │     (VerticalScroll)
│  │ Warnings / hints / marked-set info                                                │    │
│  └────────────────────────────────────────────────────────────────────────────────┘    │
│  j/k navigate · / filter · Tab state · m mark · a/r/c lifecycle · Ctrl+D delete · q close │  ← footer hint
└───────────────────────────────────────────────────────────────────────────────────────┘
```

### Key design elements

1. **Full-screen container**: `width: 95%; height: 90%`, `border: double $primary`. Matches the premium feel of
   `NotificationModal`/`MentorReviewModal` while keeping our existing `double` border (vs `thick`) for the title-bearing
   look.
2. **Header band** (top, full width, `height: auto`):
   - Title (existing `Label`).
   - **State-filter tabs**: a segmented `Static` showing `active / archived / closed / all` with the active filter
     highlighted (bold/reverse) and the rest dimmed — mirrors `NotificationModal`'s `#notification-tag-tabs`. Cycled by
     the existing Tab / Shift+Tab bindings (no binding changes). This makes the filter state obvious at a glance instead
     of buried in a text summary.
   - **Counts**: total + per-state counts rendered as a clean stats line on the same band.
3. **Filter input**: keep `FilterInput`, restyled to sit in the header band.
4. **Column header row**: a new dim/bold `Static#project-management-columns` directly above the list, labeling
   `NAME · STATE · CLAIMS · LAUNCH · WARN · WORKSPACE`. Column widths are factored into **shared width constants** in
   `project_management_rendering.py` so the header and every `record_label` row stay perfectly aligned (single source of
   truth).
5. **Project list**: `OptionList`, `height: 1fr` so it grows to fill the screen (replacing `max-height: 18`), bordered
   with a `Projects` border-title. Rows widened to use the new space: longer name field, a colored state badge,
   claims/launch/warn columns, and a much longer (less-truncated) workspace path.
6. **Detail pane**: `Static` wrapped in `VerticalScroll#project-management-detail`, fixed sensible height (e.g.
   `height: 30%` with a `min-height`), bordered with a `Details` border-title, `scrollbar-gutter: stable`. Richer
   content: project name + colored ● state badge heading, a key/value line, warnings section, marked-set info, and the
   reactivation hint — same information as today, just laid out with clearer visual hierarchy.
7. **Footer**: keep a single centered hint line (`footer_text`), regrouped/abbreviated so it reads cleanly at full width
   and degrades gracefully on narrow terminals (`text-overflow`).

### What stays exactly the same (deliberately, to limit risk)

- Every keybinding and action (j/k, /, Tab/Shift+Tab, m, u, e, a, r, c, Ctrl+D, F, Enter, R, q/Esc).
- All lifecycle logic in `ProjectManagementActionsMixin` and all `*_status` / confirmation message helpers.
- Filtering logic (`_apply_filters`), marking, force/blocked flow, reload.
- Data source (`list_project_records` / `ProjectRecordWire`).

## Files to change

1. **`src/sase/ace/tui/modals/project_management_modal.py`**
   - Rework `compose()` to emit the header band (title + state tabs + counts + filter), the new column-header `Static`,
     the `OptionList`, the `VerticalScroll`-wrapped detail, and the footer.
   - Add small refresh helpers for the new state-tabs / column-header statics; wire them into the existing
     `_refresh_options` / `_update_summary` paths. No changes to actions or bindings.
2. **`src/sase/ace/tui/modals/project_management_rendering.py`**
   - Introduce shared column-width constants.
   - Update `record_label` to use them + wider fields + a state badge.
   - Add `state_tabs_text(state_filter, counts)` and `column_header_text()` helpers.
   - Refine `summary_text` (counts line) and `detail_text` (clearer hierarchy). Footer regroup.
3. **`src/sase/ace/tui/styles.tcss`** (lines ~545–599)
   - Replace the container block with the full-screen layout: container `width: 95%; height: 90%`; header
     `height: auto`; new `#project-management-columns`; list `height: 1fr` (drop `max-height: 18`); detail as scrollable
     fixed-height pane (drop `max-height: 10`); footer with overflow-safe styling. Add border-titles.
4. **Tests**
   - `tests/ace/tui/visual/test_ace_png_snapshots.py` (or a new sibling `test_ace_png_snapshots_projects.py`): add PNG
     snapshot tests. Seed deterministic projects by monkeypatching
     `sase.ace.tui.modals.project_management_modal.list_project_records` to return fixtures built with the existing
     `make_project_record` helper, then open the modal (`page.app.push_screen(ProjectManagementModal())` or the
     leader-`p` path) and `assert_page_png`. Cover: full list at `120x40`, and a narrow `60x30` to prove graceful
     degradation. Add a `project_records()` fixture to the visual helpers.
   - Re-check existing `test_project_management_modal_*.py` still pass; adjust only assertions that hard-code old layout
     strings (e.g. exact summary/footer text), preserving behavioral intent.
   - Generate goldens with `just test-visual --sase-update-visual-snapshots` and eyeball them for beauty.

## Out of scope / non-goals

- No change to project lifecycle semantics, data model, or `sase-core`.
- No new keybindings or options (so the `?` help modal and `default_config.yml` need no updates).
- No switch to `DataTable` (keep `OptionList`).

## Risks & mitigations

- **Existing behavior tests assert exact rendered strings** → keep helper function names/signatures stable; update only
  presentational assertions, run the full `tests/ace/tui/modals/` suite.
- **Column alignment drift** → single shared width-constant source feeds both header and rows.
- **Layout overflow on small terminals** → percentage sizing + `1fr` + `text-overflow: clip` + a narrow visual snapshot
  to lock it in.
- **Visual snapshot nondeterminism** → reuse the pinned-font/color `conftest.py` harness and `wait_for_visual_idle`.

## Verification

- `just install` then `just check` (lint + mypy + tests) — required after file changes.
- `just test-visual` (and `--sase-update-visual-snapshots` once, to create goldens).
- Manual smoke via `/run` or `sase ace`: open with leader-`p`, confirm full-screen layout, filter tabs cycle, list fills
  the screen, detail/warnings/marks render, all actions still work.

## Decision I'm making as design lead

Full-width list + bottom detail (not a left/right split), because project rows are column-dense and a wide aligned table
is more readable and more beautiful here than a squeezed sidebar. If you'd prefer the left-list/right-detail split (à la
NotificationModal) instead, that's a small layout swap — say the word and I'll adjust before implementing.
