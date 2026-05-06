---
legend: sdd/legends/202605/artifacts_panel_redesign.md
epic: 5
title: Artifacts Panel Redesign Epic 5 Detail Renderers Empty States And Reliability
bead_id: sase-24.5
tier: epic
legend_bead_id: sase-24
create_time: 2026-05-06 00:50:21
status: wip
prompt: sdd/prompts/202605/artifacts_panel_epic5.md
---

# Artifacts Panel Redesign Epic 5 Plan

## Objective

Implement Epic 5, "Detail Renderers, Empty States, And Reliability", from
`sdd/legends/202605/artifacts_panel_redesign.md`.

This epic should make the artifact panel's right pane and failure modes feel trustworthy after the relationship
navigator work from Epic 3 and the row indicators from Epic 4. The implementation should stay in Python/Textual unless a
missing Rust query field is discovered. Backend graph semantics, paging, search, summaries, and manual sync/rebuild
already exist and should be treated as upstream contracts.

## Current Context

Relevant completed prerequisites in this checkout:

- `ArtifactPanelModal` already loads `artifact_show_paged` by default, keeps a compatibility `show_func` path, supports
  per-group paging, global search, local filtering, apostrophe row jumps, graph preview/export, and one targeted refresh
  for missing start artifacts.
- `ArtifactDetailPagedWire` carries `type_counts`, paged child/outbound/inbound summaries, diagnostics, payloads, and a
  legacy projection into `ArtifactDetailWire`.
- `sase artifact sync` already exists as a friendly alias for explicit historical sync/backfill, and docs mention that
  it is manual and not run from `sase ace`.
- Existing renderer tests cover kind-level detail renderers, basic file previews, image fallback, missing files,
  diagnostics, relationship summary, and a stale preview worker case.

Key gaps this epic should close:

- File artifacts are still rendered primarily as generic `kind = file`; the detail pane does not consistently use the
  canonical file type taxonomy: `plan`, `diff`, `chat`, `project`, `prompt`, `misc`.
- The detail pane has a broad "Graph links" summary, but not the compact relationship-context strip requested by the
  legend.
- Missing artifact UX mentions indexing in general, but does not clearly explain the artifact ID, likely cause, and the
  explicit manual sync/rebuild command.
- Error handling exists, but SQLite busy/read failures and stale/cancelled worker races need a clearer contract and
  broader tests around rapid navigation, filtering, and search-result navigation.

## Non-Goals

- Do not run broad `artifact_rebuild` or `sase artifact sync` from the modal.
- Do not change Rust graph semantics, file-type classification, or directory invariants unless a focused bug is found.
- Do not add per-row `artifact_show` calls or replace the paged detail contract.
- Do not redesign the left-pane relationship navigator; Epic 3 owns that surface.
- Do not rework CLs/Agents artifact indicators; Epic 4 owns those rows.
- Do not remove graph preview/export (`g`/`G`) or the compatibility `show_func` injection path used by tests.

## Cross-Phase Technical Direction

- Keep right-pane rendering lazy. Large file reads and syntax highlighting must remain off the hot navigation path.
- Prefer small renderer helpers under `src/sase/ace/tui/modals/artifact_panel_renderers/` over growing
  `artifact_panel_modal.py`.
- If a renderer needs paged counts, pass a small modal-local render context rather than teaching renderers to query the
  backend.
- Preserve history stacks across recoverable failures. A failed load should not erase `back_stack` or `forward_stack`.
- Treat all agent runtimes uniformly; file type and relationship metadata are SASE graph concepts, not provider-specific
  UI branches.
- Each implementation phase should run `just install` first in this workspace before validation and finish with focused
  tests. The final phase should run `just check`.

## Phase 5.1: File-Type Detail Renderer Taxonomy

Goal: render file artifacts by canonical file type, not just by `kind = file`.

Primary ownership:

- `src/sase/ace/tui/modals/artifact_panel_renderers/_files.py`
- `src/sase/ace/tui/modals/artifact_panel_renderers/_common.py`
- `src/sase/ace/tui/modals/artifact_panel_renderers/_detail.py`
- `tests/ace/tui/modals/test_artifact_panel_renderers.py`

Implementation shape:

- Add a small helper that resolves the effective file type from `metadata[ARTIFACT_FILE_TYPE_METADATA_KEY]`, with
  backwards-compatible fallback to `misc` for generic file artifacts.
- Split the file renderer into type-specific metadata sections:
  - `plan`: plan preview, path, source agent/planner metadata when present.
  - `diff`: diff stats and diff preview.
  - `chat`: transcript/response preview and conversation metadata when present.
  - `project`: project file summary and parsed project metadata already present on the node.
  - `prompt`: prompt preview and prompt/source metadata.
  - `misc`: generic file metadata.
- Keep one shared preview implementation for text/image/missing/empty/read-error paths so the phase does not duplicate
  file-reading logic.
- Add lightweight diff stats derived from the preview content or file content already read for preview; do not add a
  second full-file read.
- Ensure unknown future file types render gracefully as generic file artifacts with the unknown type visible.

Acceptance checks:

- Renderer tests cover all six canonical file types.
- Existing image, missing-file, empty-file, diffish-text, and line-limit tests still pass.
- A file artifact with no file type renders as `misc`.
- Large previews remain capped by existing byte/line limits and lazy syntax rendering.

Suggested verification:

```bash
just install
pytest tests/ace/tui/modals/test_artifact_panel_renderers.py -q
```

## Phase 5.2: Detail-Pane Relationship Context Strip

Goal: add a compact relationship context strip that mirrors header counts and surfaces strongest relationship hints
without duplicating the left navigator.

Primary ownership:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_state.py`
- `src/sase/ace/tui/modals/artifact_panel_renderers/_summaries.py`
- `src/sase/ace/tui/modals/artifact_panel_renderers/__init__.py`
- `tests/ace/tui/modals/test_artifact_panel_modal.py`
- `tests/ace/tui/modals/test_artifact_panel_renderers.py`

Implementation shape:

- Introduce a small render-context value object if needed, carrying:
  - children loaded/total count
  - outbound counts by link type
  - inbound counts by link type
  - type counts from `ArtifactDetailPagedWire`
  - parent/path information already loaded in detail
- Pass this context from `ArtifactPanelModal._build_detail_renderable()` to the default renderer without breaking tests
  that inject `detail_renderer(detail)`.
- Add a "Context" strip near the top of the detail pane after the artifact header and before the kind-specific body.
- Show compact hints for parent/path, children, created-by/created, related, worker, and inbound relationships when
  present.
- Prefer counts and one or two peer IDs/titles, not a full list. The left navigator remains the relationship list.
- Use existing color/badge vocabulary where possible, but keep the strip readable when Rich color is disabled.

Acceptance checks:

- Detail pane shows relationship context for parent/path, children, created, related, worker, and inbound cases.
- The strip uses paged totals where available, not just currently loaded rows.
- Injected custom renderers used by tests remain compatible.
- No backend query is issued while rendering the context strip.

Suggested verification:

```bash
pytest tests/ace/tui/modals/test_artifact_panel_modal.py tests/ace/tui/modals/test_artifact_panel_renderers.py -q
```

## Phase 5.3: Missing Index And Manual Sync UX

Goal: make unresolved artifact opens actionable while preserving the existing bounded targeted-refresh behavior.

Primary ownership:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/artifact_graph_refresh.py`
- `tests/ace/tui/modals/test_artifact_panel_modal.py`
- `tests/ace/tui/test_artifact_panel_launch.py`
- optional doc touch only if user-facing wording in `docs/artifacts.md` or CLI help is inconsistent

Implementation shape:

- Keep the current one-shot targeted refresh on missing start artifacts.
- If the artifact remains missing after targeted refresh, render a clear state in both left and right panes:
  - the exact missing artifact ID
  - the context path or artifact directory used for targeted refresh when available
  - likely reason: not indexed yet, historical artifacts not synced, source moved/deleted, or index unavailable
  - suggested commands: `sase artifact sync -j` for historical backfill, or `sase artifact rebuild -j -t <path>` /
    `sase artifact sync -j -a <artifact_dir>` when the modal has a specific context
- Do not turn the suggested commands into automatic actions.
- Avoid noisy notifications for normal missing historical artifacts; keep the message in the modal.
- Ensure the missing state still preserves modal history and lets `b`, `f`, `r`, and closing work normally.

Acceptance checks:

- Missing-after-refresh tests assert the ID, likely reason, and manual command are visible.
- Targeted refresh is called at most once per artifact ID.
- The modal does not call broad rebuild/sync from missing-state rendering.
- Navigating away from and back to a missing artifact preserves history behavior.

Suggested verification:

```bash
pytest tests/ace/tui/modals/test_artifact_panel_modal.py tests/ace/tui/test_artifact_panel_launch.py -q
```

## Phase 5.4: Load Error, SQLite Busy, And Worker Race Hardening

Goal: make recoverable backend and worker failures deterministic and non-destructive to modal state.

Primary ownership:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_state.py`
- `tests/ace/tui/modals/test_artifact_panel_modal.py`

Implementation shape:

- Add a tiny error-classification helper for user-facing load/search/page/render errors. It should recognize common
  SQLite busy/locked/read-only/read errors from exception text without importing sqlite-specific internals from Rust.
- Render SQLite busy/locked states as recoverable, with a concise "try again shortly" style message.
- Preserve `ArtifactPanelNavigationState` history stacks on load errors. Only clear current detail/paged model for the
  failing artifact.
- Stamp load, page, search, and render workers with the artifact ID/query/group they belong to and ignore late results
  if they no longer match current modal state.
- Ensure filter changes while a load or render worker is in flight cannot cause a stale preview to overwrite the newer
  detail.
- Ensure opening a search result while the previous detail render is still running cannot let the old render win.

Acceptance checks:

- Tests cover SQLite busy/locked text in load and search paths.
- Tests cover rapid navigation where a late load result is ignored.
- Tests cover filter changes during a slow render.
- Tests cover opening a search result while the previous render worker is stale.
- Back/forward stacks survive recoverable load errors.

Suggested verification:

```bash
pytest tests/ace/tui/modals/test_artifact_panel_modal.py -q
```

## Phase 5.5: Integration Polish And Epic Validation

Goal: integrate the previous phases, fill small visual/state gaps, and leave a clean handoff for Epic 6.

Primary ownership:

- Cross-cutting fixes in `src/sase/ace/tui/modals/artifact_panel_modal.py`
- Cross-cutting renderer fixes under `src/sase/ace/tui/modals/artifact_panel_renderers/`
- `src/sase/ace/tui/styles.tcss` only for focused state/contrast polish
- `tests/ace/tui/modals/test_artifact_panel_modal.py`
- `tests/ace/tui/modals/test_artifact_panel_renderers.py`
- `tests/ace/tui/test_artifact_panel_launch.py`
- optional SDD tale under `sdd/tales/202605/` if the project convention expects an implementation handoff note

Implementation shape:

- Review loading, empty, missing, indexing-needed, error, and search-error states as one visual system.
- Keep text concise and operational; avoid in-app tutorial copy beyond concrete recovery commands for missing artifacts.
- Ensure the right-pane context strip, file-type renderer headings, and diagnostics do not create duplicate or
  contradictory sections.
- Confirm graph preview/export still replace the detail pane intentionally and do not leave stale render workers able to
  overwrite them.
- Add final regression coverage for:
  - modal open on existing artifact
  - modal open on missing artifact after targeted refresh failure
  - rapid relationship navigation
  - global search result open
  - high-degree node with paged relationships
  - file-type preview cases
- Run the full repository check after installing dependencies in this workspace.

Acceptance checks:

- All Epic 5 acceptance criteria from the legend are covered by tests or explicit handoff notes.
- No broad artifact sync/rebuild occurs from modal open, render, missing-state display, search, or hot navigation.
- Existing Epic 3 and Epic 4 tests remain green.
- `just check` passes.

Suggested verification:

```bash
pytest tests/ace/tui/modals/test_artifact_panel_modal.py \
  tests/ace/tui/modals/test_artifact_panel_renderers.py \
  tests/ace/tui/test_artifact_panel_launch.py -q
just check
```

## Phase Dependencies And Agent Boundaries

Recommended order:

1. Phase 5.1 first. It is mostly isolated to file renderers and creates the file-type vocabulary used by later detail
   polish.
2. Phase 5.2 second. It may adjust the renderer call shape and should land before missing/error visual states are
   finalized.
3. Phase 5.3 and Phase 5.4 can run in parallel after Phase 5.2 if their agents coordinate carefully:
   - Phase 5.3 owns missing/indexing-needed states.
   - Phase 5.4 owns worker/error-state mechanics.
4. Phase 5.5 lands last and should only perform integration fixes, visual cleanup, docs/tale handoff if needed, and
   validation.

Avoid overlapping write scopes where possible:

- Phase 5.1 owns `_files.py` and file renderer tests.
- Phase 5.2 owns relationship context helpers and renderer call plumbing.
- Phase 5.3 owns missing/manual-sync copy and targeted-refresh failure tests.
- Phase 5.4 owns worker identity/error classification tests and modal state mechanics.
- Phase 5.5 may touch all Epic 5 files, but only after earlier phases have landed.

## Risks And Mitigations

- Risk: renderers need paged totals but only receive legacy `ArtifactDetailWire`. Mitigation: introduce a small optional
  render context passed by the modal; keep default construction from legacy detail for direct renderer tests.
- Risk: missing UX accidentally encourages automatic broad sync. Mitigation: commands are suggestions only; tests should
  monkeypatch rebuild/sync paths and assert no broad calls.
- Risk: worker-race fixes break custom injected test renderers. Mitigation: preserve the existing one-argument
  `detail_renderer(detail)` injection path and adapt only the default renderer.
- Risk: right-pane sections become repetitive. Mitigation: context strip uses counts and strongest hints only; full
  relationship lists stay in the left navigator.
- Risk: SQLite error matching becomes brittle. Mitigation: classify only common text fragments for friendlier copy, with
  a safe generic fallback.

## Final Outcome

After this epic, the artifact panel should:

- Render file artifacts by `plan`, `diff`, `chat`, `project`, `prompt`, or `misc`.
- Show a compact right-pane relationship context strip backed by loaded paged-detail summaries.
- Explain missing artifacts with concrete manual sync/rebuild guidance without running broad sync itself.
- Ignore stale workers and surface recoverable backend errors cleanly.
- Preserve navigation history, explicit graph actions, local filtering, global search, and fast hot navigation.
