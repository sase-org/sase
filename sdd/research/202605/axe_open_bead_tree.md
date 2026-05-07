# AXE Open Bead Tree Research

## Goal

Add a tree of all open SASE beads from all known projects to the AXE tab. When a bead row is selected, the right panel
should show the same detail text that `sase bead show <id>` would show for that bead in its owning project context.

## Existing AXE Tab Shape

The AXE tab is already a two-pane Textual layout:

- `src/sase/ace/tui/app.py` composes `BgCmdList` on the left and `AxeInfoPanel` plus `AxeDashboard` on the right.
- `src/sase/ace/tui/actions/axe_display/_loaders.py` owns AXE data collection, side-panel item construction,
  selection identity, and targeted refresh.
- `src/sase/ace/tui/actions/axe_display/_render.py` paints from in-memory caches. The recent navigation invariant is
  important: j/k movement must not hit disk.
- `src/sase/ace/tui/widgets/bgcmd_list.py` is misnamed for the future shape but already acts as the generic AXE
  side-panel list. Its item union currently has `AxeParentItem`, `LumberjackItem`, and `BgCmdItem`.
- `src/sase/ace/tui/widgets/axe_dashboard.py` already has separate right-panel render paths for AXE daemon summaries,
  lumberjack logs, and bgcmd output. A bead-detail render path fits this same pattern.

The lowest-risk UI integration is to extend the existing AXE side-panel item model rather than introduce a separate
tree widget. Add bead-specific item variants to `AxeItem`, extend `AxeItemKey`, and teach `_build_axe_items()` /
`_derive_axe_view_from_selection()` / `BgCmdList.update_list()` how to render and identify those rows.

## Existing Bead Read Paths

The bead CLI already routes read operations through a read view:

- `src/sase/bead/cli_query.py` implements `handle_bead_show()`. It formats the exact CLI text for status, type/tier,
  owner, assignee, parent, children, dependencies, blocks, description, notes, ChangeSpec metadata, and plan path.
- `src/sase/bead/cli_common.py` exposes `get_read_view()`, returning a `MergedBeadView` across workspace variants for
  the current project when possible.
- `src/sase/bead/workspace.py` has the important discovery primitives:
  - `get_project_beads_dirs_for_project(project_name)` resolves one known project to all readable bead stores across
    its workspaces.
  - `get_all_project_beads_dirs()` resolves bead stores for every known project, but returns a flat list without
    retaining project grouping.
  - `MergedBeadView` provides `show`, `list_issues`, `ready`, `blocked`, `stats`, and `get_epic_children` over one
    grouped set of bead directories.
- `src/sase/core/bead_read_facade.py` delegates read operations to Rust bindings, including merged read operations.

There is also a mobile bridge for all-project bead reads:

- `src/sase/integrations/_mobile_helper_beads.py` implements `beads_list_response()` and `beads_show_response()`.
- It already resolves all known projects and uses `MergedBeadView` per project group.
- It projects summary/detail wire data and has tests in `tests/test_mobile_helper_beads.py`.

The mobile bridge is useful prior art, but it should not be reused directly for the AXE tree without changes. Its
all-project list stores rows in a dict keyed only by `issue.id`, choosing the newest copy across projects. That is right
for a compact mobile response, but wrong for an AXE project tree because two projects can legally have the same bead id
prefix/counter. The AXE row identity should be `(project, bead_id)`, not just `bead_id`.

## Recommended Data Model

Add a TUI-local bead snapshot to `axe_display/_data.py` or a nearby `axe_display/_beads.py` module:

```python
@dataclass(frozen=True)
class AxeBeadProject:
    project: str
    beads_dirs: tuple[Path, ...]
    issues: tuple[Issue, ...]          # all issues needed for tree/detail context
    open_ids: frozenset[str]
    skipped_error: str | None = None

@dataclass(frozen=True)
class AxeBeadDetailSnapshot:
    project: str
    bead_id: str
    output: str
    error: str | None = None
```

Then extend `AxeCollectedData` with bead project snapshots and extend app state with:

- `_axe_bead_projects: list[AxeBeadProject]`
- `_axe_bead_detail_outputs: dict[tuple[str, str], AxeBeadDetailSnapshot]`
- `_axe_bead_detail_inflight: set[tuple[str, str]]`

The side-panel item union should grow by at least:

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

Use stable identity keys:

```python
("bead-project", project)
("bead", project, bead_id)
```

This avoids selection drift when refreshes reorder rows or when duplicate ids exist across projects.

## Building the Tree

The collector should read all known project bead groups in a background thread, matching the current AXE collector
pattern. Recommended discovery:

1. Promote the mobile helper's private project enumeration into `sase.bead.workspace`, for example
   `iter_known_project_bead_groups() -> list[tuple[str, list[Path]]]`.
2. Reuse that new function from both the mobile helper and the AXE collector.
3. For each project, open a `MergedBeadView` over that project's bead dirs and call `list_issues()`.
4. Keep all issues in the snapshot, but mark only `Status.OPEN` rows as the requested open-bead set.

Tree display choice:

- Project rows should be top-level and foldable.
- Selectable bead rows should be open beads.
- If an open bead has a non-open ancestor, include the ancestor as dim context or flatten the open bead under the
  project with a `← parent` annotation. Including non-open ancestors makes the hierarchy clearer, but those ancestor
  rows should not be counted as "open beads" or selected unless the product decision explicitly says otherwise.
- Sort projects alphabetically. Within a project, prefer hierarchy order with stable id/title fallback. Do not use
  global updated-at sorting for a tree; it makes parent/child relationships harder to scan.

## Rendering `sase bead show` Output

Do not shell out from the TUI to `sase bead show`. Extract the CLI formatter instead:

```python
def format_bead_show(view: BeadReadViewProtocol, issue_id: str, *, base_dir: Path | None = None) -> str:
    ...
```

Then `handle_bead_show()` can print that function's return value, and the AXE detail path can call the same function
with the selected project's `MergedBeadView`. This gives one source of truth for "same output" and avoids subprocess
latency, environment ambiguity, and parsing stdout/stderr.

Project context matters. `sase bead show <id>` currently resolves beads from the current working directory. In an
all-project tree, the selected row must carry its project and bead dirs, and detail rendering must use that exact
project's `MergedBeadView`. The display should be equivalent to running `sase bead show <id>` from that project's
primary workspace, not from whatever repo the AXE TUI itself was launched in.

Plan path formatting needs a small decision during extraction. The current CLI uses `os.path.relpath(issue.design)`
when SDD version-controlled mode is active. For a different selected project, `relpath` against the TUI process cwd can
be misleading. The extracted formatter should either preserve the stored design string or accept a project workspace
base directory for relative display.

## Navigation and Refresh Constraints

The AXE tab has explicit tests protecting a key performance invariant: navigation uses cached data and does not perform
disk reads. The bead implementation should preserve that:

- Full refresh: collect all project bead summaries in `asyncio.to_thread(...)` alongside the existing AXE data collector,
  then rebuild `_axe_items` from memory.
- Selection render: if the selected bead has a cached detail snapshot, render it immediately.
- Cache miss: show a short "Loading bead..." placeholder and schedule a targeted async detail read for only that bead.
- Targeted refresh (`y`): for bead rows, refresh only the selected bead's detail cache.
- Avoid precomputing `format_bead_show()` for every open bead on every refresh. It can require all-issue scans for
  `BLOCKS` and relationship sections. Compute details on demand and cache by `(project, bead_id)`.

The existing `AxeDashboard` can grow an `update_bead_display(output: str, ...)` method. Keep the exact CLI-equivalent
show text in the output section. Use `AxeInfoPanel` only for contextual status such as `Project: foo · Bead: foo-1`;
avoid duplicating fields in the right panel if that would make the "same output" claim fuzzy.

## Implementation Sketch

1. Add a reusable all-project grouped bead discovery API in `sase.bead.workspace`; update mobile helper internals to
   use it.
2. Extract `handle_bead_show()` formatting from `src/sase/bead/cli_query.py` into a pure formatter function covered by
   CLI tests.
3. Add bead snapshot collection to `axe_display/_data.py` or `axe_display/_beads.py`.
4. Extend AXE state initialization with bead list/detail caches.
5. Extend `AxeItem`, `AxeItemKey`, `_build_axe_items()`, and `_derive_axe_view_from_selection()` with bead project and
   bead rows.
6. Extend `BgCmdList` formatting for bead project rows and bead rows.
7. Extend `AxeDashboard`/`AxeInfoPanel` render methods for bead detail output.
8. Add targeted selected-bead refresh and cache-miss scheduling.

## Tests To Add

- Formatter parity: `handle_bead_show()` output equals `format_bead_show()` output for parent/children/deps/blocks and
  plan-path cases.
- All-project identity: two known projects with the same bead id both appear under separate project rows.
- AXE item restoration: selection key `(project, bead_id)` survives refresh/reorder.
- Navigation invariant: selecting/navigating bead rows does not call bead storage reads synchronously; cache-miss detail
  loading is scheduled asynchronously.
- Targeted refresh: `y` on a bead row refreshes only that bead's detail snapshot.
- Mobile bridge regression: existing `tests/test_mobile_helper_beads.py` still passes after extracting shared project
  group discovery.

## Open Questions

- Should `in_progress` beads also be shown? The request says "open", and `sase bead list --status=open` maps strictly
  to `Status.OPEN`; the implementation should start there unless UX wants an "active beads" mode.
- Should non-open ancestors be selectable when they are included for context? Recommendation: render them dim and
  non-selectable initially.
- Should the AXE tab count include open bead count? The existing AXE tab count means running lumberjacks plus bgcmd
  counts. Adding bead counts to the tab label may make the label noisy; keep bead counts in the side-panel project rows
  first.
