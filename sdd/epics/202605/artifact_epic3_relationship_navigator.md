---
create_time: 2026-05-05 22:25:43
bead_id: sase-24.3
tier: epic
legend_bead_id: sase-24
status: done
prompt: sdd/prompts/202605/artifact_epic3_relationship_navigator.md
---
# Epic 3 Relationship Navigator Modal Plan

## Context

Epic 3 from `sdd/legends/202605/artifacts_panel_redesign.md` is the Textual modal redesign for the unified artifact
graph. Epic 1 and Epic 2 appear to have already created the backend prerequisites this epic needs:

- `sase.core.artifact_facade.artifact_show_paged()` returns `ArtifactDetailPagedWire` with current node, payloads,
  path-to-root, diagnostics, child/outbound/inbound pages, group summaries, and type counts.
- `artifact_search()` accepts `ArtifactQueryWire(text=..., kinds=..., file_types=..., limit=..., offset=...)` for global
  artifact search.
- `sdd/tales/202605/artifact_epic2_phase26_handoff.md` explicitly says Epic 3 should use `artifact_show_paged`, not
  legacy `artifact_show`, for the relationship navigator.
- The current modal still calls legacy `artifact_show`, builds all relationship rows in Python, applies a global 100-row
  cap, and renders low-information one-line labels.

This plan splits Epic 3 into six sequential phases. Each phase is intended to be completed by a distinct agent instance
after approval. The phases are ordered to minimize conflict: first build a paged data spine, then row/layout rendering,
then interactive features, then visual and regression hardening.

## Non-Goals

- Do not change Rust core behavior unless an Epic 2 contract bug is discovered.
- Do not run broad artifact rebuilds or historical sync from the modal.
- Do not implement CLs/Agents artifact indicators; that is Epic 4.
- Do not replace the `OptionList` widget unless Textual makes the required behavior impossible.
- Do not change the right-pane detail renderer beyond compatibility needed for paged detail; Epic 5 owns richer detail
  rendering.

## Cross-Phase Technical Direction

Use these conventions across every phase:

- Keep the modal's primary relationship loading path on
  `artifact_show_paged(index_path, artifact_id, ArtifactPageRequestWire(...))`.
- Preserve graph preview/export (`g`/`G`) as explicit bounded actions.
- Preserve targeted refresh for missing artifacts; a modal open may attempt targeted refresh once, but must not invoke
  broad `artifact_rebuild`.
- Keep `/` as local filtering over loaded relationship rows only.
- Use a separate global search flow bound to `S`.
- Keep selectable navigator rows one line, with truncation/compact metadata instead of wrapping.
- Prefer small, testable helpers in `src/sase/ace/tui/modals/artifact_panel_state.py` and `artifact_panel_modal.py` over
  putting all logic in event handlers.
- Use the shared jump hint helper in `src/sase/ace/tui/actions/navigation/jump_hints.py` for apostrophe mode.

## Phase 3.1: Paged Data Spine And Compatibility Adapter

Goal: make the modal consume the Epic 2 paged detail contract without changing the user-facing row design yet.

Primary files:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_state.py`
- `tests/ace/tui/modals/test_artifact_panel_modal.py`
- `tests/ace/tui/test_artifact_panel_launch.py`
- possible small helpers in `src/sase/core/artifact_wire/` only if conversion gaps are found

Work:

1. Add an injected `show_paged_func` path to `ArtifactPanelModal` and make the default load path call
   `artifact_show_paged`, not `artifact_show`.
2. Keep a temporary compatibility path for tests or callers that still inject `show_func`; the default product path must
   use paged detail.
3. Add a modal-local model that stores:
   - current `ArtifactDetailPagedWire`
   - a preview-compatible `ArtifactDetailWire` projection for existing detail renderers
   - loaded relation pages keyed by group key/relation/link type
   - per-group offsets and totals
4. Ensure missing-artifact targeted refresh still retries the same paged load once.
5. Update performance/regression tests so modal open and j/k movement do not call legacy `artifact_show`,
   `artifact_list`, `artifact_search`, `artifact_summary`, or rebuild functions.

Acceptance:

- Opening the modal uses one paged detail call for the current artifact.
- Existing right-pane detail rendering still works by projecting paged relationships into the legacy detail renderer
  shape.
- High-degree nodes no longer require loading hundreds of rows on initial open.
- Existing history, parent/root, edit-file, graph preview/export, and missing-targeted-refresh behavior still passes
  tests.

Suggested verification:

- `pytest tests/ace/tui/modals/test_artifact_panel_modal.py tests/ace/tui/test_artifact_panel_launch.py`

## Phase 3.2: Header, Layout, And Rich Row Model

Goal: introduce the new persistent "where am I?" header and the richer row model while keeping paging behavior simple.

Primary files:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_state.py`
- `src/sase/ace/tui/styles.tcss`
- `tests/ace/tui/modals/test_artifact_panel_modal.py`

Work:

1. Replace the single title label with a header region containing:
   - primary line: type badge, display title, compact status/provenance/source marker
   - secondary line: compressed breadcrumb/path-to-root
   - tertiary strip for children/outbound/inbound/type counts when room allows
2. Extend `ArtifactPanelRow` with the fields requested by the legend:
   - `artifact_id`
   - `artifact_kind`
   - `file_type`
   - `edge_direction`
   - `link_type`
   - `title`
   - `subtitle`
   - `updated_label`
   - `group_key`
   - page action metadata
3. Add renderer helpers that convert rows to Rich `Text`:
   - badge + title + compact subtitle + dim right-side ID/status when space allows
   - stable labels for `plan`, `diff`, `chat`, `project`, `prompt`, `misc`
   - stable labels for `agent`, `cl`, `commit`, `bead`, `dir`, `root`, `thought`
4. Update CSS so the left pane can grow up to about 50% of the modal while retaining a practical min width.
5. Keep group headers disabled and visibly distinct with counts, but leave collapsibility out of scope.

Acceptance:

- Header remains visible during navigation/filtering/loading/error states.
- Navigator rows are one-line and contain semantic badges, titles, compact metadata, and dim IDs/status.
- Tests cover header rendering, row model construction, and group header counts.

Suggested verification:

- `pytest tests/ace/tui/modals/test_artifact_panel_modal.py`

## Phase 3.3: Per-Group Paging, Show More, And Local Filter Semantics

Goal: replace the global row cap with independent per-group pagination.

Primary files:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_state.py`
- `tests/ace/tui/modals/test_artifact_panel_modal.py`
- `tests/perf/bench_artifact_graph.py` if benchmark expectations need updating

Work:

1. Render at most 10 loaded rows per group by default.
2. Add a selectable `show more` row for any group whose loaded count is less than total count.
3. Selecting `show more` should request the next page for that group:
   - children: `ArtifactPageRequestWire(relation="children", offset=N, limit=10)`
   - outbound: `relation="outbound", link_type=...`
   - inbound: `relation="inbound", link_type=...`
4. Append or replace the group page predictably and preserve highlight where possible.
5. Define local filter behavior explicitly:
   - `/` filters the currently loaded neighborhood.
   - If a filter is active, the modal does not automatically fetch every page from the backend.
   - Clearing the filter restores normal paged rows and current group offsets.
6. Add high-degree tests proving one huge group does not hide other groups.

Acceptance:

- There is no global 100-row cap.
- Each group independently shows 10 rows plus a show-more action when more exist.
- Opening a show-more row fetches only that group page.
- Local filtering does not requery the backend and does not run global search.

Suggested verification:

- `pytest tests/ace/tui/modals/test_artifact_panel_modal.py`
- `pytest tests/perf/bench_artifact_graph.py -q` if touched

## Phase 3.4: Global Search Flow

Goal: add modal-global artifact search separate from local row filtering.

Primary files:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_state.py`
- `tests/ace/tui/modals/test_artifact_panel_modal.py`
- possibly `src/sase/ace/tui/modals/__init__.py` only if a small nested modal is introduced

Work:

1. Bind `S` in `ArtifactPanelModal` to a global search mode.
2. Implement the search UI as either:
   - an inline search input/state in the same modal, or
   - a small child modal that returns an artifact ID.
3. Use `artifact_search(index_path, ArtifactQueryWire(text=query, limit=...))`; do not search by calling `artifact_show`
   per row.
4. Render results with the same row renderer as relationship rows, but group them as search results and mark them as
   search rows.
5. Opening a search result must call `_navigate_to`, preserve back/forward stacks, and clear only state that would be
   misleading after navigation.
6. Keep `/` local filtering and `S` global search clearly separated in footer hints and tests.

Acceptance:

- Pressing `/` never calls `artifact_search`.
- Pressing `S` and entering a query calls `artifact_search` with a bounded limit.
- Selecting a result navigates through the same history path as relationship rows.
- Search loading/empty/error states are visible and recoverable.

Suggested verification:

- `pytest tests/ace/tui/modals/test_artifact_panel_modal.py`

## Phase 3.5: Apostrophe Row Navigation

Goal: add artifact-panel-local row jump behavior consistent with CLs/Agents and notification modal behavior.

Primary files:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_state.py`
- `tests/ace/tui/modals/test_artifact_panel_modal.py`
- optionally mirror focused pure tests from `tests/test_notification_modal_jump.py`

Work:

1. Bind `apostrophe` to `jump_to_entry` in the artifact panel modal.
2. Track local jump-mode state:
   - hint-to-row-id
   - row-id-to-hint
   - last row target for back-jump
3. Generate hints for currently visible selectable rows, including relationship rows, show-more rows, and global search
   result rows.
4. Render hint prefixes with the row renderer without breaking one-line row layout.
5. While jump mode is active:
   - valid hint highlights/navigates to that row without opening it unless existing tab behavior expects immediate
     selection
   - apostrophe jumps back to the previous artifact-panel row target when available
   - apostrophe falls back to hint `1` when no previous target exists
   - escape exits jump mode without closing the modal
6. Ensure `enter` remains the activation path after jump selection.

Acceptance:

- Apostrophe mode works for normal relationship rows, show-more rows, and search results.
- Escape cancels jump mode without dismissing the modal.
- Repeated apostrophe toggles between the last two row targets where possible.
- Footer hints show jump mode and return to normal after exit.

Suggested verification:

- `pytest tests/ace/tui/modals/test_artifact_panel_modal.py tests/test_notification_modal_jump.py`

## Phase 3.6: Visual Polish, Empty States, And Final Regression Pass

Goal: make the redesigned modal cohesive and verify the full Epic 3 acceptance criteria.

Primary files:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_state.py`
- `src/sase/ace/tui/styles.tcss`
- `tests/ace/tui/modals/test_artifact_panel_modal.py`
- documentation or tale files only if the implementation agent is asked to write a handoff note

Work:

1. Consolidate badge and edge style mappings for:
   - file types: `plan`, `diff`, `chat`, `project`, `prompt`, `misc`
   - non-file types: `agent`, `cl`, `commit`, `bead`, `dir`, `root`, `thought`
   - edge types/directions: parent/path, children, created, worker, related, inbound
2. Add polished loading, missing artifact, indexing-needed, empty relationship, empty search, search error, and backend
   error states.
3. Check modal rendering at small and normal terminal sizes so header/hints/rows do not overlap.
4. Keep the palette varied and restrained; avoid a single-hue theme.
5. Run the full relevant regression suite and `just check`.

Acceptance:

- The modal satisfies all Epic 3 bullets from the legend:
  - persistent header
  - left pane up to 50%
  - one-line rich rows
  - counted groups
  - per-group paging
  - separate local filter/global search
  - apostrophe row navigation
  - visual type/edge polish
- Startup and modal open paths still avoid broad artifact scans/rebuilds.
- `just check` passes in the workspace after `just install`.

Suggested verification:

- `just install`
- `pytest tests/ace/tui/modals/test_artifact_panel_modal.py tests/ace/tui/test_artifact_panel_launch.py`
- `pytest tests/perf/bench_artifact_graph.py -q`
- `just check`

## Phase Handoff Rules

Each agent should start by reading:

- `memory/short/build_and_run.md`
- `memory/short/glossary.md`
- `memory/short/gotchas.md`
- `memory/short/rust_core_backend_boundary.md`
- `sdd/legends/202605/artifacts_panel_redesign.md`
- `sdd/tales/202605/artifact_epic2_phase26_handoff.md`
- this plan file

Each phase should leave:

- passing targeted tests for the changed surface
- no broad startup artifact graph calls
- no runtime-specific behavior
- no automatic historical sync/rebuild from `sase ace`
- a concise final note listing changed files and any remaining phase-specific risks

## Open Questions For Approval

1. Should global search be inline in the existing modal or a child modal? Inline keeps context visible; a child modal
   may be cleaner and easier to test.
2. Should jump hints merely highlight rows or immediately activate rows? CLs/Agents highlights the target; the artifact
   panel should probably highlight and keep Enter as activation, but show-more rows may feel better if they execute
   immediately.
3. Should local filter search only loaded pages, or should it offer an explicit "search all artifacts with S" hint when
   no local rows match? This plan chooses loaded pages only to preserve boundedness.
