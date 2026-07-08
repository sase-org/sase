---
create_time: 2026-07-07 20:52:33
status: done
prompt: sdd/prompts/202607/zoom_panel_file_list.md
---
# Plan: Zoom Panel File List — Freeze, Clarify, and Beautify

## Problem / Context

The Agents-tab **zoom modal** (`z` on a selected agent) shows one detail panel at a time (METADATA / FILE / TOOLS).
Inside the FILE panel the user cycles through the agent's files with `<ctrl+n>` / `<ctrl+p>`. Three problems were
reported:

1. **Invisible list.** There is no on-screen list of the available files. The only affordance is a terse header counter
   (`⛶ ZOOM - FILE (2/5) · notes.md`). The user cannot see _what_ files are in the list, only a position number.
2. **The list mutates during navigation.** After pressing `z`, the file list is _not_ frozen. A mount-time refresh plus
   a recurring 2–10s timer re-derive the list from live agent state, so the set of entries (and the current selection)
   can change out from under `<ctrl+n>`/`<ctrl+p>`.
3. **Wrapping feels broken.** `<ctrl+n>`/`<ctrl+p>` should wrap first↔last.

The user asked us to lead the design and make it **intuitive, reliable, and beautiful**.

### Terminology note (important design framing)

In the current code `<ctrl+n>`/`<ctrl+p>` cycle **files within the FILE panel**, while `]`/`[` cycle **panels**
(METADATA/FILE/TOOLS). The report says "files/panels" loosely because each file is shown in a panel. We interpret the
three asks as primarily about the **file list** cycled by `<ctrl+n>`/`<ctrl+p>`, and we additionally give the _panel_
dimension a clear affordance (a header tab strip) so both "which files" and "which panels" are obvious. Both
file-cycling and panel-cycling already wrap; this plan keeps and reinforces that.

## Root-cause analysis

- **Issue 2 (list mutates) is the real defect.** Relevant code:
  - `src/sase/ace/tui/modals/zoom_panel_modal.py::on_mount` starts a `set_interval` timer that calls
    `_refresh_active_panel(force=False)` every `max(refresh_interval, 2)` seconds, and also refreshes once at mount.
  - `src/sase/ace/tui/modals/zoom_panel_content.py::refresh_file` re-derives the list each tick: for a terminal agent it
    calls `panel.set_file_list(agent.all_files, …)`; for an active agent it calls `panel.update_display(...)` →
    `_reconcile_file_list` → `_desired_file_list`.
  - The **seed** list captured at open (`src/sase/ace/tui/actions/agents/_panel_detail.py::_zoom_seed_from_detail`,
    `file_list = tuple(getattr(file_panel, "_file_list", ()))`) is built by `_desired_file_list` and can contain
    **synthetic slot IDs** (`_LIVE_DIFF_SENTINEL`, `commit_slot_id(...)`, `linked_slot_id(...)`), whereas
    `agent.all_files` (`src/sase/ace/tui/models/agent.py`) is only `[diff_path] + extra_files` (raw paths). Because the
    two lists differ, `set_file_list`'s no-op guard (`src/sase/ace/tui/widgets/file_panel/_file_list.py`) fails, the
    list is rebuilt, and the current index can snap. This happens on the first refresh at mount and can recur on later
    ticks.

- **Issue 3 (wrapping) is already implemented.** `next_file`/`prev_file` in
  `src/sase/ace/tui/widgets/file_panel/_file_list.py` advance `(_current_file_index ± 1) % len(...)`, and there are
  passing tests (`test_zoom_next_file_wraps_last_to_first`, `test_zoom_prev_file_wraps_first_to_last`). The _perception_
  that it doesn't wrap is a **symptom of Issue 2**: when the list rebuilds/renumbers mid-navigation, wrapping looks
  inconsistent. Freezing the list (Issue 2 fix) makes wrapping deterministic. We will also add explicit regression
  tests.

- **Issue 1 (invisible list) is a UX gap.** The modal renders only the current file's content plus a header counter
  (`_update_header` in `zoom_panel_modal.py`). There is no list widget.

## Goals

- Freeze the file list at the moment the FILE view first appears in the zoom modal; navigation and background refresh
  must never add/remove/reorder entries or move the selection.
- Show a clear, always-present, beautiful list of the files with the active one obviously highlighted.
- Make panel membership (METADATA/FILE/TOOLS) and the active panel obvious.
- Keep `<ctrl+n>`/`<ctrl+p>` wrap-around reliable and covered by tests.

## Non-goals

- No changes to how the base (non-zoom) Agents detail file panel behaves.
- No new keymaps (reuse `z`, `<ctrl+n>`/`<ctrl+p>`, `]`/`[`). No `default_config.yml` change.
- No Rust core changes. Per the repo's `rust_core_backend_boundary`, this is presentation-only Textual state —
  snapshotting a list for a modal session and rendering it is a TUI concern. File-list _derivation_
  (`_desired_file_list`, `all_files`) already lives in Python and is unchanged.

---

## Design

Three coordinated pieces. Piece 1 is the correctness backbone; pieces 2–3 are the clarity/beauty layer.

### 1) Freeze the file list on activation (reliability)

**Principle:** once the zoom modal first shows a populated FILE list, that ordered list of entries and the selection
semantics are locked for the life of the modal. Background refresh may still re-render the _content_ of the
currently-selected entry (e.g. a running agent's growing live diff) and update the agent status, but it must never
mutate the list structure or jump the selection.

**Mechanism** — add a "frozen" mode to the zoom-only `ZoomFilePanel` (`src/sase/ace/tui/modals/zoom_panel_widgets.py`),
which subclasses `AgentFilePanel`. This reuses the existing, well-tested reconciliation/scroll/trim machinery instead of
duplicating it:

- Add `_file_list_frozen: bool` and a captured snapshot, plus `freeze_current_list()` which records the current
  `_file_list` / `_current_file_index` and sets the flag.
- **Override `_desired_file_list(agent)`**: when frozen, return the frozen snapshot (and a stable default). Because
  `_reconcile_file_list` / `update_display` compute `desired` via this method, a frozen panel always sees
  `desired == _file_list`, so the existing "stable list" branch runs — it keeps the list/index fixed while still
  re-rendering the current entry when a live/linked diff's _content_ changes (preserving scroll). No list churn is
  possible through this path.
- **Override `set_file_list(...)`**: when frozen, never replace the list or move the index; only display the current
  entry if nothing has been displayed yet (first paint), else no-op. This blocks the terminal-agent `refresh_file` path
  (`set_file_list(agent.all_files, …)`) from swapping the frozen slot-ID list for raw `all_files` — and preserves the
  user's trim (`=`/`-`) exactly as today.
- Expose a read-only `is_file_list_frozen` for tests.

**When freezing happens (two tiers):**

- _Common path (FILE visible at open):_ the seed carries `file_list`. In `zoom_panel_content.py::seed_panels`, after
  copying the seed list/index into the panel, call `freeze_current_list()`. This is the authoritative "all files
  available at the moment" snapshot, because the base panel already reconciled the full canonical list (commit slots +
  live diff + linked slots + extra files) before `z` was pressed.
- _Lazy path (FILE revealed later, or `has_file_content` with no seed list):_ the first `refresh_file` that yields a
  non-empty list runs the normal build once, then calls `freeze_current_list()`. Covers reveal-from-metadata (`<ctrl+n>`
  from METADATA → `reveal_file_panel`) and seed-less `has_file_content` cases.

`refresh_file`'s existing active/terminal branching is **unchanged**; the freeze is enforced by the `ZoomFilePanel`
overrides, so every caller is covered defensively. `next_file`/`prev_file` operate directly on `_file_list` (the frozen
list) and keep their existing modulo wrap.

**Known limitation (documented, acceptable):** in the lazy reveal path, if a _running_ agent's primary diff has not been
fetched/cached at the instant of reveal, the frozen snapshot may omit the live-diff entry until the modal is reopened.
The common path (FILE already visible at `z`) is unaffected because the base panel's list is already complete. This edge
is called out as a possible follow-up.

### 2) File rail — a beautiful, always-visible list (clarity)

Add a slim **vertical file rail** on the left of the FILE view: the classic "file list + preview" layout. It lists every
frozen entry; the active entry is unmistakably highlighted.

- **New widget** `ZoomFileRail(Static)` in `zoom_panel_widgets.py` with an `update_entries(entries, active_index)`
  method that builds a Rich `Text`:
  - Each row: a small source-type tag/icon + a short label. Active row: leading marker (e.g. `▸`), bold, accent
    background bar; inactive rows: dim, no marker. Long labels are truncated.
  - Rail border title: `FILES (n)`. Active row is scrolled into view when the list is long.
- **Labels/icons** come from generalizing the existing `current_source_label()` in
  `src/sase/ace/tui/widgets/file_panel/_file_list.py` into a reusable per-slot helper that maps any slot → (type tag,
  label): live diff → "diff"; commit slot → `repo short_sha` (+ workspace marker for non-primary); linked slot →
  workspace marker + repo name; plain path → basename. Reuse the existing `WORKSPACE_GLYPH` (`▣`). **Glyph safety:** the
  visual suite pins Fira Code; prefer glyphs already used in this codebase (`▸ ● ▣ · │`) and verify via a new PNG
  snapshot. Keep icons minimal — lean on the text label — to stay legible and font-safe.
- **Visibility rule:** the rail shows only when the FILE target is active **and there are 2+ entries**. For a single
  file (the common case) the rail is collapsed (`display: none`) and the FILE content spans full width — so the existing
  single-file behavior and its PNG snapshot are unchanged.

**Layout / structural change.** Today `#zoom-file-scroll` is toggled directly by the target machinery. To seat a rail
beside it, wrap the file scroll and the rail in a Horizontal `#zoom-file-view`:

```
#zoom-file-view (Horizontal, carries the `hidden` toggle for the FILE target)
├── #zoom-file-rail  (ZoomFileRail; `collapsed` when <2 entries)
└── #zoom-file-scroll (VerticalScroll; unchanged id → ZoomFilePanel content)
```

Because several places toggle visibility per target via `#zoom-{target}-scroll`, introduce one shared helper — a
per-target **view selector** (FILE → `#zoom-file-view`; others → `#zoom-{target}-scroll`) — and use it in:

- `src/sase/ace/tui/modals/zoom_panel_navigation.py::show_target` (the `_TARGET_ORDER` hide/show loop).
- `src/sase/ace/tui/modals/zoom_panel_search.py::_show_zoom_search_overlay` / `_hide_zoom_search_overlay` (so the search
  overlay correctly hides the rail-bearing wrapper too).

`active_scroll` continues to return `#zoom-file-scroll` (the inner scroll still exists), so scrolling, search, focus,
and the reveal/undo logic keep working. New CSS in `styles.tcss` for `#zoom-file-view`, `#zoom-file-rail` (fixed-ish
width, green FILE-theme border, `collapsed`/`hidden` states), and making the inner `#zoom-file-scroll` take `width: 1fr`
within the wrapper.

**Rail refresh triggers:** update the rail wherever the list/selection/target changes — from `on_file_list_changed`
(posted by `next_file`/`prev_file`/reconcile) and from `show_target`. Simplest: call a new `_update_rail()` at the end
of `_update_header()` (already invoked from all the right places); it collapses the rail when the target isn't FILE or
the count ≤ 1, else renders entries + active index.

### 3) Panel tabs in the header (clarity for "panels")

Rewrite `_update_header()` in `zoom_panel_modal.py` to render the available targets as a compact **tab strip**:
`METADATA · FILE · TOOLS` with the active target highlighted (bold; background tinted to match that panel's border color
— FILE green, TOOLS `#87D7FF`, METADATA accent), inactive targets dimmed. The active FILE tab carries the compact
counter (`FILE 3/5`). This replaces the terse `(position/total)` text and makes both panel membership and the active
panel obvious at a glance, complementing the file rail. The right-hand agent label + status is unchanged.

---

## Changes by file

- `src/sase/ace/tui/modals/zoom_panel_widgets.py` — add `_file_list_frozen`, `freeze_current_list()`,
  `is_file_list_frozen`, and overrides of `_desired_file_list` / `set_file_list` on `ZoomFilePanel`; add the new
  `ZoomFileRail(Static)` widget.
- `src/sase/ace/tui/modals/zoom_panel_content.py` — freeze in `seed_panels` (seed path) and after the first non-empty
  build in `refresh_file` (lazy path). Otherwise leave `refresh_file` branching intact.
- `src/sase/ace/tui/modals/zoom_panel_modal.py` — compose the `#zoom-file-view` wrapper + `#zoom-file-rail`; rewrite
  `_update_header()` for panel tabs + counter; add `_update_rail()`; call it from the header update. Update the hints
  line only if needed.
- `src/sase/ace/tui/modals/zoom_panel_navigation.py` — add the shared per-target **view selector** helper; use it in
  `show_target`.
- `src/sase/ace/tui/modals/zoom_panel_search.py` — use the shared view selector in the overlay show/hide so the rail
  wrapper is hidden with the FILE view during search.
- `src/sase/ace/tui/widgets/file_panel/_file_list.py` — extract a reusable per-slot label/icon helper (generalize
  `current_source_label`) for the rail; no behavior change to the base panel.
- `src/sase/ace/tui/styles.tcss` — styles for `#zoom-file-view`, `#zoom-file-rail` (border/active-row/collapsed), inner
  scroll `width: 1fr`, and the header tab strip (mostly Rich-styled in Python, minimal CSS).

## Testing plan

Unit/interaction tests (`tests/ace/tui/`, using the existing `_agents_zoom_panel_helpers.py`):

- **Freeze:** after opening with a seeded list, a periodic `refresh_active_panel(force=False)` (and a simulated live
  agent whose `all_files` differs from the seeded slot-ID list) leaves `_file_list` and `current_file_index` unchanged;
  `is_file_list_frozen` is true. Verify a running-agent tick still refreshes the current live-diff content while the
  list stays fixed.
- **Wrap-around:** keep/extend `test_zoom_next_file_wraps_last_to_first` / `test_zoom_prev_file_wraps_first_to_last`;
  add a "wrap survives a refresh tick between presses" test to lock the Issue-2/Issue-3 interaction.
- **Reveal/undo:** existing reveal tests must still pass; update any assertions that check `#zoom-file-scroll`
  hidden-class to target `#zoom-file-view` (the wrapper now carries `hidden`).
- **Rail:** with 2+ files the rail is visible, lists all entries, and marks the active index; with 1 file the rail is
  collapsed. Rail active index follows `<ctrl+n>`/`<ctrl+p>`.
- **Search + rail:** starting search hides the FILE view (rail included); exiting restores it.

Visual PNG snapshots (`tests/ace/tui/visual/`, goldens in `.../snapshots/png/`):

- The existing single-file FILE snapshot (`agents_file_zoom_modal_120x40.png`) keeps its layout (rail collapsed); only
  the header **text** changes (tabs). Regenerate affected zoom goldens (`agents_metadata/context/file/waiting_unknown` +
  search) with `--sase-update-visual-snapshots` and visually verify — the diff should be limited to the header strip.
- Add a **new multi-file fixture + snapshot** (agent with a diff + 2 extra files) exercising the rail so the beautiful
  list rendering and glyph choices are pinned.

## Docs & help

- Update `src/sase/ace/tui/modals/help_modal/agents_bindings.py` "Zoom Modal" section to describe the file rail, panel
  tabs, and the frozen-on-open behavior (respecting the 57-char box formatting rule and the "keep `?` help in sync"
  convention in `src/sase/ace/CLAUDE.md`).
- Update the "Agents Zoom Panel" section of `docs/ace.md` to document: the list is fixed on open, `<ctrl+n>`/`<ctrl+p>`
  cycle files with wrap-around, `]`/`[` cycle panels, and the rail/tabs.

## Out of scope / follow-ups

- Mouse click-to-select in the rail (navigation stays keyboard-driven for now).
- Re-syncing the frozen list to newly-appeared files without reopening (intentionally fixed per the request); the
  running-agent-reveal edge above could be revisited if it bites in practice.

## Risk & rollout

- Highest-risk area is the `#zoom-file-view` wrapper interacting with the target/search machinery; contained by routing
  all per-target visibility through one shared view-selector helper and by keeping `#zoom-file-scroll` (the scroll id
  everything else queries) intact.
- The freeze reuses existing reconciliation/trim/scroll code paths rather than duplicating them, so behaviors like
  "show-all survives periodic refresh" are preserved.
- Verify with `just check` and the visual suite; drive the modal end-to-end (open on a multi-file agent, cycle with
  wrap, confirm the list/selection never change across refresh ticks, confirm rail + tabs highlight correctly, confirm
  single-file and search still render correctly). </content> </invoke>
