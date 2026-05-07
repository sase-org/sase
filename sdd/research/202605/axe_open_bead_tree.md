# AXE Open Bead Tree Research

## Goal

Add a tree of all open SASE beads from all known projects to the AXE tab. When a bead row is selected, the right panel
should show the same detail text that `sase bead show <id>` would show for that bead in its owning project context.

## Existing AXE Tab Shape

The AXE tab is already a two-pane Textual layout:

- `src/sase/ace/tui/app.py` (the `AxeMixin` composition) places `BgCmdList` on the left and `AxeInfoPanel` plus
  `AxeDashboard` on the right.
- `src/sase/ace/tui/actions/axe_display/_loaders.py` owns AXE data application, side-panel item construction,
  selection identity, and targeted refresh:
  - `_load_axe_status_async()` (line 188) — full async refresh.
  - `_refresh_selected_axe_item_async()` (line 199) — targeted `y` refresh; currently only handles lumberjack and
    bgcmd selections.
  - `_schedule_targeted_axe_refresh()` (line 259) — wraps the above for the `y` keymap.
  - `_build_axe_items()` (line 359) — rebuilds the flat side-panel list and restores selection by identity.
  - `_derive_axe_view_from_selection()` (line 408) — sets `_axe_current_view` based on the selected item.
- `src/sase/ace/tui/actions/axe_display/_render.py` paints from in-memory caches. There is an explicit invariant
  enforced by `tests/ace/tui/test_axe_navigation.py` (e.g. `test_navigation_does_not_read_from_disk`,
  `test_update_axe_tab_count_does_not_read_from_disk`): j/k navigation and tab-count derivation must not perform
  per-row disk reads. New bead rows must respect this same invariant.
- `src/sase/ace/tui/actions/axe_display/_data.py` defines the collector `collect_axe_status_data()` and the
  `AxeCollectedData` dataclass that carries snapshot caches into the apply step. New bead snapshots belong here.
- `src/sase/ace/tui/widgets/bgcmd_list.py` is the side-panel widget. Its `AxeItem` union today is exactly:
  `AxeParentItem()`, `LumberjackItem(name: str)`, `BgCmdItem(slot: int)`. It already renders nested children with a
  Unicode tree connector (`"  └─ "`), so indentation-based hierarchy already exists — there is no need to introduce
  a Textual `Tree` widget.
- `src/sase/ace/tui/widgets/axe_dashboard.py` already has separate right-panel render paths for AXE daemon summaries,
  lumberjack logs, and bgcmd output. A bead-detail render path fits this same pattern.
- `AxeViewType` in `_data.py` is `Literal["axe"] | int` (int = bgcmd slot). It must be extended to carry a bead view
  identity (e.g. `tuple[Literal["bead"], str, str]` for `(project, bead_id)`).

The lowest-risk UI integration is to extend the existing AXE side-panel item model rather than introduce a separate
tree widget. Add bead-specific item variants to `AxeItem`, extend `AxeItemKey`, and teach `_build_axe_items()` /
`_derive_axe_view_from_selection()` / `BgCmdList.update_list()` how to render and identify those rows. Selection
restoration already flows through `sase.ace.tui.util.selection.restore_selection_by_identity` with an `identity_fn`,
so new rows just need to plug into `_axe_item_key()`.

Folding is handled by `FoldStateManager` (`_axe_fold_manager`), keyed today by the literal string `"axe"`. Per-project
folds for the bead tree should reuse this manager with keys like `("bead-project", project)`; do not invent a parallel
fold mechanism.

## Existing Bead Read Paths

The bead CLI routes read operations through a merged view, but the show formatter is **not** factored out today:

- `src/sase/bead/cli_query.py` — `handle_bead_show(args)` is a single 80-line function (lines 34–115) that:
  1. Calls `view.show(args.id)` and prints the status/title header.
  2. Prints type/tier/owner line, optional assignee, optional epic count.
  3. Recursively `view.show(parent_id)` to print the PARENT section.
  4. For PLAN issues, calls `view.get_epic_children(...)` and prints CHILDREN.
  5. For each `dependency.depends_on_id`, calls `view.show(dep_id)` to print DEPENDS ON entries.
  6. Calls `view.list_issues()` to compute BLOCKS, then `view.show(bid)` per block to print titles.
  7. Prints DESCRIPTION, NOTES, optional CHANGESPEC (PLAN-only: name, bug id), and PLAN (design path).
  8. The PLAN path uses `os.path.relpath(issue.design)` only when `sase.sdd.beads.get_sdd_config()` returns truthy
     (SDD versioned mode); otherwise prints `issue.design` verbatim.

  This is N+1 read calls per show. For a TUI that wants a CLI-equivalent string per selection, the natural
  refactor is to precompute one `view.list_issues()` and an `issue_by_id` dict (the mobile bridge already does this
  in `_bead_detail_wire`/`_bead_summary_wire`) and have the formatter consume that dict instead of calling back into
  the view per relation.

- `src/sase/bead/cli_common.py` — `get_read_view()` returns a `MergedBeadView` (or single `BeadProject`) for the
  current CWD-inferred project. **It does not accept a project override.** `sase bead show` has no `-p/--project`
  flag today, which means "same output" for an arbitrary project must be defined as: equivalent to running
  `sase bead show <id>` from that project's primary workspace. A clean prerequisite step is to add `-p PROJECT`
  to `sase bead show` (and other read subcommands) so the CLI and the TUI share one definition of project context.

- `src/sase/bead/workspace.py`:
  - `get_project_beads_dirs()` — current-project, CWD-inferred (line 20).
  - `get_project_beads_dirs_for_project(project_name)` — explicit project, no CWD inference (line 32).
  - `get_all_project_beads_dirs()` — flat union of every known project's bead dirs (line 46). **Does not retain
    project grouping.**
  - `MergedBeadView` (line ~212) — context manager that delegates to Rust via `bead_read_facade` for `show`,
    `list_issues`, `ready`, `blocked`, `stats`, `get_epic_children`.

- `src/sase/core/bead_read_facade.py` — Rust binding wrappers; merged variants are `merged_show`, `merged_list_issues`,
  `merged_ready`, `merged_blocked`, `merged_stats`, `merged_get_epic_children`. There is no tree/hierarchy formatter
  in the facade — the TUI is responsible for any hierarchical rendering on top of `list_issues()`.

The mobile bridge already has reusable scaffolding that should be promoted instead of rebuilt:

- `src/sase/integrations/_mobile_helper_beads.py`:
  - `_BeadReadScope` (line 32) — a frozen dataclass that already preserves `groups: tuple[(project, beads_dirs), ...]`
    with project identity intact.
  - `_resolve_bead_read_scope(request)` (line 136) — the entry point used by both `beads_list_response` and
    `beads_show_response`.
  - `_explicit_project_scope`, `_all_known_project_scope`, `_known_project_names` (lines 150, 190, 215) — the
    project-grouped enumeration logic.

  The mobile bridge does, however, **dedupe by `issue.id` alone** at the projection step (`beads_list_response` line
  74–77) when collapsing multi-project results into a single mobile list. For an AXE tree this is wrong — two
  projects can legally share an id like `1.2`. The grouped scope is reusable; the projection is not.

Recommendation: extract a public helper in `sase.bead.workspace`:

```python
def iter_known_project_bead_groups() -> list[tuple[str, list[Path]]]: ...
```

…then have `_mobile_helper_beads._all_known_project_scope` and the new AXE collector both consume it. This removes
duplicated `~/.sase/projects/*` enumeration and keeps one definition of "all known projects."

## Open Bead Semantics

`sase.bead.model.Status` has three values: `OPEN`, `IN_PROGRESS`, `CLOSED`.

- `sase bead list --status=open` is a strict filter — `Status.OPEN` only.
- `sase bead list` with no `--status` defaults to `[Status.OPEN, Status.IN_PROGRESS]`
  (`cli_query.py:18`). The mobile helper's `_bead_status_filter` (line 335) follows the same default when
  `include_closed=False`.

For the AXE tree, "open" should map to the strict `Status.OPEN` interpretation matching the literal request, with a
follow-up question for the user (see Open Questions) about whether `IN_PROGRESS` should also be shown by default.
Either way, store the full issue set in the snapshot — `sase bead show` for any selected bead needs all issues anyway
to compute BLOCKS, and downstream filters (status, type, tier) should run from the snapshot, not from re-reads.

## Recommended Data Model

Add a TUI-local bead snapshot to `axe_display/_data.py` (or a sibling `axe_display/_beads.py` if `_data.py` grows
unwieldy):

```python
@dataclass(frozen=True)
class AxeBeadProject:
    project: str
    beads_dirs: tuple[Path, ...]
    all_issues: tuple[Issue, ...]
    open_ids: frozenset[str]
    skipped_error: str | None = None

@dataclass(frozen=True)
class AxeBeadDetailSnapshot:
    project: str
    bead_id: str
    output: str          # CLI-equivalent text from format_bead_show()
    error: str | None = None
```

Extend `AxeCollectedData` with `bead_projects: tuple[AxeBeadProject, ...]` and add app state in `app.py`:

- `_axe_bead_projects: list[AxeBeadProject]`
- `_axe_bead_detail_outputs: dict[tuple[str, str], AxeBeadDetailSnapshot]`
- `_axe_bead_detail_inflight: set[tuple[str, str]]`

Side-panel item union additions in `bgcmd_list.py`:

```python
@dataclass(frozen=True)
class BeadProjectItem:
    project: str

@dataclass(frozen=True)
class BeadItem:
    project: str
    bead_id: str
    depth: int
    title: str
    status: Status
    issue_type: IssueType
    tier: BeadTier | None
    parent_id: str | None
    selectable: bool = True
```

Identity keys (extend `AxeItemKey`):

```python
("bead-project", project)
("bead", project, bead_id)
```

`AxeViewType` becomes:

```python
AxeViewType = Literal["axe"] | int | tuple[Literal["bead"], str, str]
```

…where the tuple carries `(project, bead_id)`. `_derive_axe_view_from_selection()` and the targeted-refresh path
must learn to dispatch on this tuple form.

## Building the Tree

The collector reads all known project bead groups in a background thread, matching the current AXE collector pattern.
Recommended discovery:

1. Add `iter_known_project_bead_groups()` (or equivalent) in `sase.bead.workspace`. Update
   `_mobile_helper_beads._all_known_project_scope` to consume it; ensure `tests/test_mobile_helper_beads.py` still
   passes.
2. For each project, open a `MergedBeadView` over that project's bead dirs and call `list_issues()` once. Store the
   full list in the snapshot; mark `Status.OPEN` ids as the "requested open set."
3. Build an `issue_by_id: dict[str, Issue]` per project once and use it for tree linkage and (later) detail
   formatting.

Tree display rules:

- Project rows are top-level and foldable via `FoldStateManager` keyed by `("bead-project", project)`.
- Selectable bead rows are open beads. If an open bead has a non-open ancestor, include the ancestor as dim,
  non-selectable context to keep the hierarchy legible — do **not** silently flatten the tree, because epics with
  closed plans would otherwise look like orphaned phases.
- Sort projects alphabetically. Within a project, prefer hierarchy order (epic → plan → phase) with stable id/title
  fallback. Avoid global updated-at ordering for a tree — it scrambles parent/child relationships.
- Empty projects (no open beads) should still appear in collapsed form with `(0)` so users know they're being
  scanned. Skip projects whose `MergedBeadView` failed and surface the error in the snapshot's `skipped_error`.

## Rendering `sase bead show` Output

Do **not** shell out from the TUI. The handler is currently inline; extract a pure formatter:

```python
def format_bead_show(
    issue: Issue,
    *,
    issue_by_id: Mapping[str, Issue],
    sdd_versioned: bool,
    project_workspace: Path | None = None,
) -> str: ...
```

Design notes for the extraction:

- **Take resolved data, not a view.** Pass `issue` plus an `issue_by_id` dict. The formatter walks the dict for
  PARENT / CHILDREN / DEPENDS ON / BLOCKS instead of calling `view.show()` per relation. This collapses the current
  N+1 reads to one snapshot per project and makes the function trivially testable.
- **Keep CLI parity.** `handle_bead_show` calls the formatter and prints its return value. A snapshot test should
  pin the byte-for-byte output across PARENT, CHILDREN, DEPS, BLOCKS, NOTES, CHANGESPEC, PLAN sections.
- **PLAN path display.** `handle_bead_show` calls `os.path.relpath(issue.design)` only when `get_sdd_config()` is
  truthy. For an arbitrary selected project, `relpath` against the TUI process CWD is misleading. The extracted
  formatter should accept `project_workspace: Path | None`; if SDD-versioned and a workspace is provided, compute
  `os.path.relpath(issue.design, project_workspace)`; otherwise fall back to the stored design string. Have the AXE
  caller pass the project's primary workspace (the parent of the representative beads dir, computed the same way as
  `_workspace_display` in the mobile helper, line 404–412).
- **CHANGESPEC section** is PLAN-only and shows `changespec_name` and/or `changespec_bug_id`. Don't drop it —
  ChangeSpec metadata is one of the things users actually want to see in the right panel.

The existing `AxeDashboard` should grow an `update_bead_display(output: str, ...)` render path. Keep the formatter's
exact text in the output section; reserve `AxeInfoPanel` for short context like `Project: foo · Bead: foo-1`. Avoid
duplicating bead fields in both panels — that would muddy the "same output as `sase bead show`" claim.

## Project Context Resolution

`sase bead show` today resolves beads from CWD via `get_read_view()`. There is no `-p/--project` flag. Two paths:

1. **Recommended prerequisite:** add `-p/--project` to `sase bead {show,list,ready,blocked,stats}` so the CLI itself
   can render any known project's beads. The TUI then has a clean meaning for "same output." Per
   `memory/short/gotchas.md`, every new option needs a short flag, so use `-p`.
2. **Without that prerequisite:** define "same output" as "equivalent to running `sase bead show <id>` from that
   project's primary workspace." That is implementable but harder to test against the CLI directly.

Either way, the TUI's selected row carries `(project, bead_id)` and detail rendering uses that exact project's
`MergedBeadView`. Project workspace is recoverable from the representative beads dir using the same logic as
`_workspace_display` in `_mobile_helper_beads.py`.

## Navigation and Refresh Constraints

Preserve the documented invariant from `tests/ace/tui/test_axe_navigation.py`:

- **Full refresh:** collect all project bead summaries inside the `asyncio.to_thread(collect_axe_status_data)` call
  (or an adjacent collector if isolation is preferred), then rebuild `_axe_items` from memory.
- **Selection render:** if `(project, bead_id)` has a cached detail snapshot, render it immediately. j/k must never
  trigger a synchronous read.
- **Cache miss:** show a short `Loading bead…` placeholder and schedule an async detail read for only that bead. Use
  `_axe_bead_detail_inflight` to dedupe concurrent requests for the same key.
- **Targeted refresh (`y`):** extend `_refresh_selected_axe_item_async()` so a `("bead", project, bead_id)` view
  reloads only that bead's detail by re-opening the project's `MergedBeadView` in a thread.
- **Lazy detail computation.** The full BLOCKS/PARENT/CHILDREN walk is cheap once `issue_by_id` is in memory, but
  formatting all open beads on every refresh wastes work. Compute on demand and cache by `(project, bead_id)`.
- **Project-level `list_issues()` is shared.** When multiple beads of the same project miss cache in quick
  succession, reuse the project's `all_issues` snapshot from the most recent collector run — don't re-open the
  view per bead.

The existing tab-count logic (`_update_axe_tab_count`) currently shows running lumberjacks + bgcmds. Adding open-bead
totals to the tab label risks visual noise; instead show per-project counts on `BeadProjectItem` rows in the side
panel. Revisit the tab label only if users ask.

## Implementation Sketch

1. Promote `_known_project_names` / project-grouped enumeration from `_mobile_helper_beads.py` into
   `sase.bead.workspace` as `iter_known_project_bead_groups()`. Update mobile helper internals to use it.
2. Extract `handle_bead_show` formatting into `format_bead_show(issue, *, issue_by_id, sdd_versioned,
   project_workspace=None)` in `sase/bead/cli_query.py` (or a sibling `cli_show_format.py`); keep the CLI command as
   a thin wrapper that prints the return value. Add a snapshot test pinning the formatter's output.
3. (Recommended prerequisite) Add `-p/--project` to `sase bead show` (and peer read commands), routed through
   `get_project_beads_dirs_for_project`.
4. Add `AxeBeadProject` / `AxeBeadDetailSnapshot` to `axe_display/_data.py`; extend `AxeCollectedData` and
   `collect_axe_status_data()` accordingly.
5. Extend AXE app state with bead list and detail caches (and inflight set).
6. Extend `AxeViewType`, `AxeItem`, `AxeItemKey`, `_axe_item_key()`, `_build_axe_items()`,
   `_derive_axe_view_from_selection()`, and `_refresh_selected_axe_item_async()`.
7. Extend `BgCmdList` with formatting for `BeadProjectItem` and `BeadItem` (reuse existing tree-connector
   indentation; add depth-based prefixes).
8. Add `AxeDashboard.update_bead_display()` and an `AxeInfoPanel` context line for bead selections.
9. Wire targeted refresh and cache-miss scheduling for bead rows.
10. Update the `?` help modal (`help_modal.py`) and the keybinding footer per
    `src/sase/ace/AGENTS.md`: any new bead-related keymap that is conditional on selection type goes in the footer
    (sorted alphabetically, named keys lowercase angle-bracketed); global ones go in the help modal only. Respect
    the 57-char box width.

## Tests To Add

- **Formatter parity:** `format_bead_show()` output equals current `handle_bead_show` stdout for a representative
  fixture covering parent / children / deps / blocks / changespec / plan-path (both SDD-versioned and not).
- **All-project identity:** two known projects with the same bead id appear under separate project rows; selecting
  each renders its own detail.
- **Project enumeration parity:** mobile bridge `tests/test_mobile_helper_beads.py` continues to pass after the
  shared `iter_known_project_bead_groups()` extraction.
- **Selection key restoration:** `("bead", project, bead_id)` survives full-refresh reorder; mirrors existing
  selection identity tests for lumberjack/bgcmd rows.
- **Navigation invariant extension:** add a bead variant of `test_navigation_does_not_read_from_disk` —
  monkeypatch `MergedBeadView` / `bead_read_facade` reads to raise, then assert j/k across bead rows never invokes
  them after the initial collector run.
- **Targeted refresh:** `y` on a `("bead", p, id)` view re-reads only that bead's project, not all projects.
- **Cache-miss scheduling:** selecting an uncached bead shows a placeholder and schedules an async load; subsequent
  selections of the same bead while inflight do not enqueue duplicate work.
- **PLAN path workspace handling:** with SDD-versioned mode and a non-CWD project, the PLAN line uses the project
  workspace as the relpath base (or falls back to the stored string when no workspace is supplied).

## Open Questions

- **`Status.OPEN` only or `OPEN + IN_PROGRESS`?** The user said "open." `sase bead list --status=open` is strict;
  the no-flag default is both. Recommend starting with strict OPEN and adding a toggle if the user later wants
  active beads (then default to both, matching the CLI no-flag behavior).
- **Non-open ancestor rows.** Recommendation: show dim and non-selectable. Confirm with the user before
  implementation.
- **Tab label count.** Skip for now; show per-project counts on side-panel project rows.
- **Add `-p PROJECT` to `sase bead show` first?** Recommend yes — it gives the TUI a CLI-level definition of
  "same output" and benefits non-TUI users too. Smallish, independently shippable change.
- **Closed projects in the list.** Should we hide projects with zero open beads, render them collapsed-and-empty,
  or hide them but show a "+N more (no open beads)" footer row? Default suggestion: render collapsed with `(0)`,
  re-evaluate after dogfooding.
- **Sort within project.** Hierarchy-first vs. tier-first vs. updated-at. Hierarchy-first is the recommendation;
  confirm before implementing.

## Affected Files (for the implementer)

- `src/sase/bead/workspace.py` — new `iter_known_project_bead_groups()`.
- `src/sase/bead/cli_query.py` — extract `format_bead_show()`; add `-p/--project` if accepted.
- `src/sase/bead/cli_common.py` — possibly add a project-aware variant of `get_read_view()`.
- `src/sase/integrations/_mobile_helper_beads.py` — switch to shared enumeration helper.
- `src/sase/ace/tui/actions/axe_display/_data.py` — bead snapshot dataclasses, collector extension, view-type union.
- `src/sase/ace/tui/actions/axe_display/_loaders.py` — item building, key derivation, view derivation, targeted
  refresh.
- `src/sase/ace/tui/actions/axe_display/_render.py` — bead detail render branch.
- `src/sase/ace/tui/widgets/bgcmd_list.py` — `BeadProjectItem`/`BeadItem` and their formatters.
- `src/sase/ace/tui/widgets/axe_dashboard.py` — bead detail render path.
- `src/sase/ace/tui/widgets/axe_info_panel.py` — bead context line.
- `src/sase/ace/tui/widgets/help_modal.py` — keymap docs (per `src/sase/ace/AGENTS.md`).
- `src/sase/ace/tui/widgets/keybinding_footer.py` — conditional bead keymaps if any.
- `tests/ace/tui/test_axe_navigation.py` — extend invariant test.
- `tests/bead/...` — formatter parity test.
- `tests/test_mobile_helper_beads.py` — regression for shared enumeration.
