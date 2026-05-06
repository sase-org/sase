---
create_time: 2026-05-05 19:59:05
status: wip
prompt: sdd/prompts/202605/artifacts_panel_redesign.md
legend_bead_id: sase-24
tier: legend
epic_count: 6
---
# Artifacts Panel Redesign Plan

## Goal

Make the new artifacts panel feel like a fast, beautiful relationship navigator rather than a raw list of graph links.
The work should preserve `sase ace` startup around the old ~1s target, index newly-created artifacts automatically, and
make existing users run one explicit sync/rebuild command if their historical artifacts are missing from the unified
index.

This plan intentionally splits the work into epics that can later be subdivided into phase beads and assigned to
distinct agent instances. The highest-risk behavior lives in `../sase-core/crates/sase_core`; Python/Textual should stay
focused on presentation, wiring, and thin adapters over `sase_core_rs`.

## Current State

The artifact graph substrate already exists:

- Rust core has SQLite-backed artifact nodes, links, payloads, list/show/graph/rebuild/export, targeted rebuild inputs,
  and doctor checks.
- Python exposes `sase.core.artifact_facade`, `sase artifact ...`, and the `ArtifactPanelModal`.
- The modal is currently an `OptionList` with path, children, outbound groups, inbound groups, a local `/` filter, a
  global 100-selectable-row cap, and basic `g`/`G` graph preview/export.
- The TUI watcher can call targeted graph refreshes for changed paths, and the panel can do a one-shot targeted refresh
  when a starting artifact is missing.

The key gaps are:

- Directory semantics are too permissive. A directory should only be an artifact when it contains another non-directory
  artifact, except `/`.
- File artifacts do not yet have a first-class type taxonomy. The requested file artifact types are `plan`, `diff`,
  `chat`, `project`, `prompt`, and `misc`.
- `artifact_show` returns all immediate links/children, which forces the TUI to do local slicing and applies one global
  row cap instead of per-group paging.
- The modal has low-information rows and a black-and-white visual language.
- There is no global artifact search distinct from the local row filter.
- CLs and Agents tabs do not show artifact-count indicators.
- Startup must not do broad unified artifact graph rebuilds or broad source scans.

## Product Design

The primary UI should remain a two-pane Textual modal:

- Left pane: relationship navigator with fixed one-line rows, group counts, per-group paging, and color-coded type
  badges.
- Right pane: artifact detail and preview.
- Top: persistent "where am I?" header that summarizes the current node, root path, and relationship counts.
- Bottom: concise key hints.

The left pane should be allowed to expand up to 50% of the modal. Rows should still be compressed to one line by using
short labels, right-side dim IDs, and compact metadata. Do not rely on wrapping in the navigator.

Use a stable visual language:

- File type badges: `plan`, `diff`, `chat`, `project`, `prompt`, `misc`.
- Non-file badges: `agent`, `cl`, `commit`, `bead`, `dir`, `root`, `thought`.
- Edge direction glyphs should be semantic but unobtrusive: parent/path, children, created, worker, related, inbound.
- Status and provenance should be secondary. Use color for scanability, not decoration.
- Group headers should be visually distinct and include counts, for example `Created 37` and `Inbound related 8`.

Keep `/` as local filtering. Add a separate global artifact search/jump flow, bound inside the modal to `S` or another
available modal-local key. Local filter narrows visible neighborhood rows; global search queries the whole artifact
index and jumps through the same `_navigate_to` path so history continues to work.

Add apostrophe support in the artifact panel by matching the existing row-jump behavior from the CLs/Agents tabs:

- First apostrophe enters row-jump mode and paints short hints on visible selectable rows.
- A hint key jumps directly to that row.
- Apostrophe while in jump mode returns to the previous jump target when available, otherwise selects the first hinted
  row.
- Escape exits jump mode.

## Epic 1: Artifact Semantics And Migration Contract

Purpose: make the graph model correct before building UI on top of it.

Phase 1.1: File Type Taxonomy

- Define the canonical file artifact type set in Rust and Python constants: `plan`, `diff`, `chat`, `project`, `prompt`,
  `misc`.
- Treat file type as part of the semantic artifact type. The storage-compatible path can be either:
  - `kind = "file"` plus required `metadata.artifact_type`, with all query/UI contracts exposing `file_type`; or
  - explicit kind strings such as `file:plan` if the team wants the database kind itself to be distinct.
- The important invariant is that `file(project)`, `file(chat)`, and `file(misc)` are unrelated type buckets in search,
  filtering, grouping, and indicators.
- Update all agent-created-file classifiers:
  - plan: `plan_path`, `sdd_plan_path`, `plan_path.json` target, plan feedback where appropriate.
  - diff: `diff_path`, `commit_diff_path`, prompt-step diffs, `.diff`/`.patch`.
  - chat: chat transcripts and response/live-reply transcripts where they represent conversation output.
  - project: `.gp` project files that are represented as file artifacts.
  - prompt: `raw_xprompt.md`, `prompt.md`, `*_prompt.md`, prompt step prompts, `sdd_prompt_path`.
  - misc: every other file artifact.
- Preserve backwards compatibility for existing rows that only have `kind = "file"` by reading missing type as `misc`.

Phase 1.2: Directory Artifact Invariant

- Change Rust directory materialization so `/` is always present, and any other directory node is created only as the
  containing-directory closure of at least one non-directory artifact.
- Remove directory-only ingestion that creates standalone empty directories as artifacts.
- Ensure agent artifact directories are still created only because they contain an agent node and/or created file nodes.
- Ensure project directories, workflow directories, and bead directories remain navigable when they contain project,
  ChangeSpec, bead, agent, or file artifacts.
- Add stale cleanup or doctor diagnostics for orphan directory nodes that no longer contain non-directory artifacts.

Phase 1.3: Migration And Compatibility

- Add or document an explicit one-time historical sync path for existing users:
  - Keep `sase artifact rebuild` as the low-level command.
  - Prefer adding a friendlier alias such as `sase artifact sync` if product wording matters.
- Sync should rebuild historical derived rows and backfill file types.
- Normal `sase ace` startup must not run this sync.
- Add release-note/help text that says historical artifacts may require one manual sync; newly-created artifacts are
  indexed automatically.

Phase 1.4: Tests

- Rust tests for file type classification from all known agent/project marker paths.
- Rust tests that standalone directories are absent, `/` exists, and parent directory chains exist only for
  non-directory artifacts.
- Python wire/conversion tests for file type fields and old `file` rows.
- CLI tests proving `list` can filter by file type once the query contract exists.

## Epic 2: Fast Incremental Indexing And Query Contracts

Purpose: make the backend answer exactly what the UI needs without startup regressions.

Phase 2.1: Startup Performance Guardrail

- Audit `sase ace` startup and prove no unified artifact graph rebuild runs on first paint.
- Keep watcher setup cheap. It may register project/artifacts/beads directories, but it must not scan historical
  artifact trees at startup.
- Add a performance regression test or benchmark gate around startup paths that asserts artifact graph calls happen only
  from explicit panel/search actions or source-change events.
- Preserve the existing agent loader path that queries `agent_artifact_index.sqlite` when available and avoids full
  source scans for missing indexes before first paint.

Phase 2.2: Targeted New Artifact Indexing

- Ensure every new agent artifact directory and relevant marker write triggers a targeted unified graph refresh.
- Deduplicate bursts by artifact directory/source path and run refreshes off the UI thread.
- For created files, refresh the specific artifact directory context, not the whole projects root.
- For `.gp` files and `sdd/beads/issues.jsonl`, keep the existing targeted source handling.

Phase 2.3: Paged Detail Contract

- Add a Rust/Python query contract that can return one artifact detail plus group summaries:
  - current node
  - path-to-root
  - children count and first page
  - outbound counts/pages by link type
  - inbound counts/pages by link type
  - optional counts by artifact/file type
- Page size default should be 10 for UI groups.
- This should avoid loading hundreds of rows into the modal just to hide most of them.
- Keep `artifact_show` stable if needed; add `artifact_show_paged` or extend with optional paging input if that is less
  disruptive.

Phase 2.4: Global Search Contract

- Add query support for file types as distinct buckets.
- Make artifact search fast enough for an interactive modal: indexed text/kind/file-type filters, limit/offset, stable
  deterministic ordering.
- Return enough metadata for one-line result rows: display title, artifact type, subtitle/status, updated time, dim ID.

Phase 2.5: Artifact Indicator Summary Contract

- Add a cheap summary query for a list of artifact IDs:
  - input: ChangeSpec names and agent IDs/fallback IDs visible in the current tab.
  - output: total linked artifact count, grouped by file type and relevant non-file kind.
- The query must be batched. Do not call `artifact_show` once per visible row during list rendering.
- Cache summaries per list refresh and invalidate on targeted graph refresh.

## Epic 3: Relationship Navigator Modal

Purpose: deliver the redesigned artifacts panel itself.

Phase 3.1: Layout And Header

- Replace the single title label with a persistent header region:
  - primary line: badge, display title, status/provenance where useful.
  - secondary line: path breadcrumb compressed to fit one line.
  - tertiary metadata or edge-count strip if there is room.
- Let the left pane expand up to 50% of the modal and use measured row widths to choose a panel width within CSS bounds.
- Update `styles.tcss` so the modal has a richer but restrained palette, clear focus borders, and readable row contrast.

Phase 3.2: Row Model And Rendering

- Extend `ArtifactPanelRow` beyond `label`:
  - artifact ID
  - artifact kind
  - file type
  - edge direction
  - link type
  - title
  - subtitle/status
  - updated label
  - group key
  - page action metadata
- Render every selectable row as one line:
  - badge + title + compact subtitle + dim right-side ID/status when space allows.
  - No wrapping in the navigator.
- Make group headers counted, colored, and disabled unless they become collapsible in a later phase.

Phase 3.3: Group Paging And Show More

- Replace the global 100-row cap with per-group 10-row pages.
- Each group should show at most 10 rows plus a `show more` row when more exist.
- Selecting `show more` advances that group page or expands by another 10 rows.
- Preserve local `/` filtering behavior: filtering searches all rows in the current loaded neighborhood and should
  either reset paging or show matching rows across pages in a predictable way.
- Add tests for high-degree nodes where one huge group does not hide other groups.

Phase 3.4: Local Filter And Global Search Split

- Keep `/` focused on the current relationship navigator only.
- Add global search modal state and binding.
- Results should be visually consistent with relationship rows but grouped as search results, not as local links.
- Opening a result uses `_navigate_to`, preserves back/forward stacks, and clears local filter only when necessary.

Phase 3.5: Apostrophe Row Navigation

- Add artifact-panel-local row-jump state modeled after the CLs/Agents entry jump behavior.
- Generate hints for currently visible selectable rows, including `show more` rows and global search results.
- Apostrophe while already in jump mode should return to the previous artifact-panel row target when available, matching
  existing behavior on other surfaces.
- Update modal hints and tests.

Phase 3.6: Visual Polish

- Add type badge styles shared by the modal and row indicators.
- Use color to encode semantic type, direction, and status:
  - plan, diff, chat, project, prompt, misc each get stable colors.
  - created/worker/related/parent edges get stable accent colors.
  - warnings/diagnostics remain yellow/red.
- Keep the palette varied and avoid a monochrome theme.
- Make loading, missing artifact, indexing needed, and error states visually intentional.

## Epic 4: CLs And Agents Artifact Indicators

Purpose: surface artifact availability before the user opens the panel.

Phase 4.1: Shared Indicator Model

- Add a shared Python value object for artifact count summaries:
  - total count
  - per file type counts
  - optional non-file counts for agents, beads, thoughts, commits, etc.
  - stale/loading/error states
- Add shared renderer that produces the same visual output for CL and Agent rows.
- Keep text compact, for example: `art 8 plan2 diff1 chat3 misc2`.

Phase 4.2: Batch Summary Loader

- Load summaries once per CL list refresh and once per Agent list refresh.
- Do not load summaries in the hot j/k path.
- Cache summary data beside existing list-render state and invalidate on artifact graph refresh events.
- If the artifact index is missing or unsynced, render nothing or a dim `art ?` only where useful; do not force a
  rebuild.

Phase 4.3: CLs Tab Integration

- Extend ChangeSpec row formatting and width calculations to include the indicator.
- Include linked artifacts grouped by file type and important non-file types.
- Ensure marked, status, mentor, grouping, and jump-hint rendering still fit and patch correctly.

Phase 4.4: Agents Tab Integration

- Extend Agent row formatting and render-cache keys to include the indicator.
- Keep workflow child rows readable and do not let indicators crowd runtime suffixes.
- Ensure grouped Agents tab widths still adjust correctly and j/k remains cheap.

Phase 4.5: Tests

- Unit tests for shared indicator rendering.
- ChangeSpec and Agent list tests proving identical grouping/color semantics.
- Regression tests that hot navigation does not issue artifact summary queries.

## Epic 5: Detail Renderers, Empty States, And Reliability

Purpose: make the right pane and failure modes trustworthy.

Phase 5.1: File Detail Renderer Updates

- Render file artifacts by file type, not only by `kind = file`.
- Show type-specific headings and metadata:
  - plan: plan preview/path/source agent
  - diff: diff stats and preview
  - chat: transcript/response preview
  - project: project file summary
  - prompt: prompt preview
  - misc: generic file metadata
- Continue to use lazy rendering so large files do not block navigation.

Phase 5.2: Relationship Context In Detail Pane

- Add a compact context strip in the detail pane that mirrors the header counts and shows the strongest relationship
  hints: parent, created-by/created, related, worker.
- Keep this secondary to the left navigator; do not duplicate the entire row list.

Phase 5.3: Index Missing And Manual Sync UX

- When the panel opens on an artifact that is missing from the index, keep the existing targeted refresh attempt.
- If targeted refresh still cannot find the artifact, render a clear state:
  - missing artifact ID
  - likely reason
  - suggested `sase artifact sync` or `sase artifact rebuild` command
- Do not run broad historical sync from the modal.

Phase 5.4: Error And Concurrency Hardening

- Ensure cancelled workers cannot overwrite newer detail renders.
- Handle SQLite busy/read errors gracefully.
- Preserve history stacks across recoverable load failures.
- Add tests for rapid navigation, filter changes during load, search result open during stale render, and targeted
  refresh failure.

## Epic 6: Performance, Documentation, And Rollout

Purpose: land the redesign without regressing startup or leaving future agents guessing.

Phase 6.1: Performance Measurements

- Reproduce the reported startup regression on this machine with a small scripted measurement for `sase ace`.
- Measure before/after:
  - cold startup to first paint
  - startup with missing unified artifact index
  - panel open on existing artifact
  - panel open on missing artifact requiring targeted refresh
  - global search
  - high-degree artifact navigation with 200+ links
- Check in the benchmark script or update existing perf tests where appropriate.

Phase 6.2: Test Matrix

- Rust core tests for semantics/query contracts.
- Python facade tests for new wire contracts.
- CLI parser/handler tests for sync/search/file-type filters.
- Textual modal tests for header, row rendering, paging, search, apostrophe navigation, and no broad calls.
- CLs/Agents widget tests for indicators and no hot-path artifact queries.
- Run `just install` before validation in this workspace, then `just check`.

Phase 6.3: Documentation

- Update `/sase_artifact` skill text and CLI help for sync/rebuild.
- Add a short SDD tale after implementation with the new model:
  - directory invariant
  - file type taxonomy
  - startup indexing policy
  - UI keymap summary
- Mention the one-time sync expectation for existing users.

Phase 6.4: Rollout Safety

- Land backend semantics before UI indicators so the UI does not depend on ambiguous type data.
- Land query contracts before modal polish so the TUI does not grow temporary per-row `artifact_show` calls.
- Keep broad historical sync manual.
- Keep old `g`/`G` graph preview/export behavior unless a later dedicated graph-map epic replaces it.

## Suggested Execution Order

1. Epic 1 Phase 1.1 and 1.2: artifact semantics.
2. Epic 2 Phase 2.1 and 2.2: performance and incremental indexing.
3. Epic 2 Phase 2.3 through 2.5: query contracts.
4. Epic 3: modal relationship navigator.
5. Epic 4: CLs/Agents indicators.
6. Epic 5 and 6: detail polish, reliability, documentation, and validation.

## Non-Goals For This Round

- Do not build a force-directed graph canvas.
- Do not run broad historical indexing automatically during `sase ace` startup.
- Do not make directories first-class artifacts merely because they exist on disk.
- Do not make file type an aesthetic-only label; it must affect query/filter/grouping semantics.
- Do not replace the existing agent artifact index during this work unless a later phase explicitly plans that
  migration.

## Acceptance Criteria

- `sase ace` startup returns to roughly the previous ~1s behavior on this machine, with no broad unified artifact
  rebuild on startup.
- Newly-created artifacts are indexed automatically through targeted refresh.
- Existing users have a documented one-time manual sync/rebuild path.
- Directory artifacts obey the invariant: only `/` or directories containing non-directory artifacts.
- Every file artifact is typed as exactly one of `plan`, `diff`, `chat`, `project`, `prompt`, `misc`.
- Artifact panel left rows are one-line, grouped, colored, counted, and paged at 10 rows per group.
- The panel has a persistent "where am I?" header.
- `/` filters local rows; global search is separate.
- Apostrophe row navigation works in the artifact panel consistently with other tabs/panels.
- CLs and Agents tabs show consistent artifact indicators grouped by type without adding hot-path queries.
- `just check` passes after implementation.
