---
create_time: 2026-05-05 21:07:13
status: wip
prompt: sdd/prompts/202605/artifact_epic2_fast_indexing_query_contracts.md
---
# Epic 2 Plan: Fast Incremental Indexing And Query Contracts

## Context

This plan implements Epic 2 from `sdd/legends/202605/artifacts_panel_redesign.md`. The goal is to make the artifact
backend answer the redesigned panel's needs without regressing `sase ace` startup. The work is intentionally split into
phases that can be handled by distinct agent instances after approval.

Current useful facts:

- Artifact semantics from Epic 1 are already mostly present in `../sase-core/crates/sase_core/src/artifact/`: file type
  metadata, misc compatibility, directory-root invariant tests, `sase artifact sync`, and targeted rebuild inputs exist.
- Python exposes the graph through `src/sase/core/artifact_facade.py` and `src/sase/core/artifact_wire/`.
- The TUI has `src/sase/ace/tui/artifact_graph_refresh.py` and calls it from
  `EventHandlersMixin._schedule_artifact_graph_refresh`.
- `ArtifactWatcher` currently installs recursive watches for existing descendants at startup. That makes new deep marker
  writes visible, but it can still scan historical artifact trees while starting `sase ace`, which conflicts with Epic
  2.1.
- `artifact_show` still returns full children/outbound/inbound collections. `artifact_list` and `artifact_search`
  currently load all nodes into memory and then filter/sort in Rust, which is not the final interactive-search contract.
- No batched artifact indicator summary contract exists yet.

## Execution Model

Work these phases sequentially unless a later phase explicitly says it can branch. Each phase should leave the repo in a
passing state for its touched test slice. Because each phase will be worked by a separate agent instance, every phase
below includes ownership boundaries, handoff notes, and validation.

Before any implementation phase:

- Run `just install` in this workspace if it has not already been prepared.
- Confirm `../sase-core` is present and writable, because backend contracts belong there.
- Treat `../sase-core/crates/sase_core` as the source of truth for shared backend behavior. Python should remain a thin
  adapter over `sase_core_rs`.
- Do not add automatic broad graph rebuilds to `sase ace` startup.

## Phase 2.1: Startup Guardrails And Watcher Economics

Purpose: prove and enforce that `sase ace` first paint does not perform broad artifact graph rebuilds or broad source
scans, while keeping event watching available.

Ownership:

- `src/sase/ace/tui/actions/startup.py`
- `src/sase/ace/tui/util/fs_watcher.py`
- Startup and watcher tests under `tests/ace/tui/`
- No Rust query-contract changes in this phase.

Implementation outline:

- Add explicit tests that `AceApp._start_post_mount_background_loads()` never calls unified graph
  rebuild/list/show/search before first paint.
- Preserve the agent loader contract that prefers `agent_artifact_index.sqlite` and only does bounded Tier 1 fallback
  scans.
- Change watcher startup so it does not recursively `rglob("*")` historical artifact trees at startup. Prefer shallow
  initial watches on project dirs, project `artifacts/` dirs, `sdd/beads`, and dynamic watch installation when new
  directories are created or moved in.
- If recursive watches are still needed for correctness, add a budgeted/lazy/background mode that cannot block startup
  and is covered by timing/count tests.
- Keep changed-path delivery to `_on_artifact_change(changed_paths)` intact.

Acceptance criteria:

- Existing startup stopwatch tests still pass.
- New tests fail if startup calls `artifact_rebuild`, `artifact_list`, `artifact_show`, or a broad agent source scan
  before the post-mount background load boundary.
- Watcher tests prove newly-created nested agent artifact dirs still produce changed paths after startup.
- No broad unified graph sync is introduced anywhere in startup.

Suggested validation:

- `just test tests/ace/tui/test_startup_stopwatch_live_update.py tests/ace/tui/test_fs_watcher.py tests/ace/tui/actions/test_agent_artifact_startup_contracts.py`

## Phase 2.2: Targeted Incremental Indexing Pipeline

Purpose: make new agent artifact writes and relevant project/bead writes refresh only their bounded graph context,
deduped and off the UI thread.

Ownership:

- `src/sase/ace/tui/artifact_graph_refresh.py`
- `src/sase/ace/tui/actions/event_handlers.py`
- Watcher/event tests under `tests/ace/tui/`
- Rust targeted rebuild behavior only if a discovered bug prevents correct bounded refresh.

Implementation outline:

- Make changed-path classification explicit and testable: agent artifact directory, agent-created file context, `.gp`
  project file, `sdd/beads/issues.jsonl`, and optional direct directory/file path.
- Deduplicate by normalized refresh key, not raw event path: `("agent", artifact_dir)`, `("project", project_file)`,
  `("beads", beads_dir)`, `("directory", target_path)`.
- Ensure agent-created files refresh the containing `artifacts/<workflow>/<timestamp>` context with agent sources, not
  the projects root.
- Keep `.gp` refresh scoped to project-derived sources and bead refresh scoped to bead store sources.
- Add worker-level coalescing so one file burst schedules at most one in-flight graph refresh plus one follow-up,
  similar to existing agent refresh behavior.
- Add tests that pure selection/navigation paths never call targeted graph refresh.

Acceptance criteria:

- New marker writes under a fresh agent artifact directory lead to one bounded rebuild request with `artifact_dir=...`
  and agent source kinds.
- A burst of writes in the same artifact directory is deduped.
- `.gp` and bead changes keep their current targeted-source behavior.
- Targeted rebuild errors are logged/debug-safe and do not break TUI refreshes.

Suggested validation:

- `just test tests/ace/tui/test_artifact_graph_refresh.py tests/ace/tui/test_event_handlers_dirty_flags.py tests/ace/tui/test_fs_watcher.py`

## Phase 2.3: Paged Artifact Detail Contract

Purpose: add the backend contract the redesigned relationship navigator needs so the modal does not fetch hundreds of
rows only to slice them locally.

Ownership:

- Rust: `../sase-core/crates/sase_core/src/artifact/wire.rs`, `query.rs`, `mod.rs`, `lib.rs`
- Python binding: `../sase-core/crates/sase_core_py/src/lib.rs`
- Python wire/facade: `src/sase/core/artifact_wire/`, `src/sase/core/artifact_facade.py`
- Tests: Rust artifact query tests, `tests/test_core_facade/test_artifact.py`

Implementation outline:

- Add new wire records rather than destabilizing `ArtifactDetailWire`:
  - `ArtifactPageRequestWire`: group key or relation selector, offset, limit.
  - `ArtifactGroupSummaryWire`: group key, direction/category, link type where relevant, total count, loaded count.
  - `ArtifactRelationPageWire`: summary plus nodes/links for that page.
  - `ArtifactDetailPagedWire`: current node, payloads, path-to-root, diagnostics, children page, outbound pages by link
    type, inbound pages by link type, optional type-count summary.
- Add `artifact_show_paged(index_path, artifact_id, request)` through Rust, `sase_core_rs`, and Python facade.
- Default UI page size should be 10, but the contract should accept explicit per-call limits.
- Implement counts in SQL using indexed link tables. Avoid loading all children/links into memory for count/page
  operations.
- Keep `artifact_show` stable for existing CLI and current modal tests.
- Include deterministic ordering compatible with current row ordering.

Acceptance criteria:

- A high-degree artifact can request first page and counts per group without materializing all rows.
- Existing `artifact_show` behavior remains compatible.
- Python dataclass conversion rejects unknown fields and preserves schema version checks for new wire records.

Suggested validation:

- Rust artifact tests in `../sase-core`.
- `just test tests/test_core_facade/test_artifact.py tests/main/test_artifact_cli_read_commands.py`

## Phase 2.4: Interactive Global Search Contract

Purpose: make global artifact search fast and semantically useful for the later modal search flow.

Ownership:

- Rust query/store indexes in `../sase-core/crates/sase_core/src/artifact/`
- Python binding/facade for `artifact_search`
- CLI parser/handler only if adding an explicit `sase artifact search` command is cleaner than overloading `list`
- Search tests under Rust, facade, and main CLI tests

Implementation outline:

- Add a first-class `artifact_search` binding instead of relying on `artifact_list` as an alias.
- Move text/kind/file-type/provenance/source/root filters into SQL where possible.
- Add or migrate SQLite indexes needed for interactive search:
  - kind and display ordering
  - source/provenance filters
  - link source/target filters already exist
  - file type extraction may require a generated/cache column or a conservative metadata side table if JSON filtering is
    too slow.
- Keep ordering stable and deterministic: primary match quality if implemented, then updated/display/id fallback.
- Return enough metadata for one-line UI rows via `ArtifactNodeWire` initially. Add a compact `ArtifactSearchResultWire`
  only if the UI needs non-node fields that would otherwise require follow-up calls.
- Validate file type filters as real semantic buckets, not display-only labels.

Acceptance criteria:

- Search supports text, artifact kind, file type, limit, offset, and stable ordering.
- Search does not load the whole artifacts table into Rust memory for ordinary filters.
- Invalid file type filters fail clearly.
- Existing `sase artifact list -F` continues to work.

Suggested validation:

- Rust search/query tests.
- `just test tests/test_core_facade/test_artifact.py tests/main/test_artifact_cli_read_commands.py tests/main/test_artifact_cli_parser.py`

## Phase 2.5: Batched Artifact Indicator Summary Contract

Purpose: provide cheap summaries for CL and Agent list indicators without per-row `artifact_show` calls.

Ownership:

- Rust wire/query/binding for a batch summary API.
- Python wire/facade.
- Initial Python cache invalidation hook in TUI event layer, but no visual row rendering yet. Epic 4 owns rendering.
- Tests in Rust, facade, and a small TUI cache invalidation/unit test.

Implementation outline:

- Add `ArtifactSummaryRequestWire` and `ArtifactSummaryWire` records:
  - input IDs: ChangeSpec names, agent IDs, or generic artifact IDs.
  - output per ID: total linked artifact count, counts by file type, counts by non-file kind, missing/unsynced/error
    state.
- Implement one batched Rust query using `IN (...)` chunks or a temporary table, not N calls to `artifact_show`.
- Count immediate relevant relationships first. Include both inbound and outbound relationship counts where that is what
  CL/Agent indicators need; document exact semantics in the wire type.
- Add Python facade `artifact_summary(index_path, request)`.
- Add a lightweight cache holder or invalidation signal that later Epic 4 row renderers can reuse. Invalidate summaries
  when targeted graph refresh reports affected nodes/links or when any artifact refresh event runs.

Acceptance criteria:

- A batch of visible CL/agent IDs returns summaries in one backend call.
- Tests prove no per-row `artifact_show` calls happen in the summary path.
- Missing index or missing IDs return graceful empty/error summary states and do not trigger rebuilds.

Suggested validation:

- Rust summary tests.
- `just test tests/test_core_facade/test_artifact.py tests/ace/tui/test_event_handlers_dirty_flags.py`

## Phase 2.6: Integration Benchmarks And Handoff

Purpose: close Epic 2 with measurable performance evidence and a clean handoff to Epic 3/4 UI agents.

Ownership:

- `tests/perf/artifact_graph/`
- Focused docs or SDD tale if useful
- No new product UI beyond thin diagnostics/CLI needed for validation.

Implementation outline:

- Update the artifact graph benchmark helpers to include:
  - startup contract sentinel
  - targeted refresh burst
  - paged detail on 200+ linked rows
  - global search
  - batched summary for visible CL/agent rows
- Keep benchmark scripts optional for normal unit runs unless an existing perf gate expects them.
- Document the final contracts and intended consumers for Epic 3 and Epic 4:
  - `artifact_show_paged` for relationship navigator
  - `artifact_search` for modal-global search
  - `artifact_summary` for CL/Agent indicators
  - targeted refresh invalidation behavior
- Run full repo validation after `just install`: `just check`.

Acceptance criteria:

- Benchmarks or perf tests show startup does not call broad unified artifact graph rebuilds.
- High-degree detail, search, and summary operations are bounded by explicit limits.
- Handoff notes are clear enough for UI agents to consume the contracts without reverse-engineering the Rust layer.

Suggested validation:

- Targeted perf command for artifact graph benchmarks.
- `just check`

## Cross-Phase Risks

- Watcher correctness versus startup cost: recursive startup watching is convenient but risky. Prefer shallow startup
  plus dynamic watch registration for new directories.
- Wire churn: phases 2.3 through 2.5 all touch wire files. Land them sequentially to avoid conflicts.
- SQLite JSON filtering: file type lives in node metadata today. If SQL JSON extraction is not reliable across supported
  SQLite builds, add a derived indexed column/table rather than falling back to all-node scans.
- UI temptation: avoid building Epic 3 modal behavior during Epic 2. Add only minimal CLI/facade surfaces needed to
  prove backend contracts.
- Existing users: do not hide slow historical rebuilds in startup. Manual `sase artifact sync`/`rebuild` remains the
  migration path.

## Done Definition For Epic 2

- `sase ace` startup has tests proving no broad unified artifact rebuild before first paint.
- New artifact writes are incrementally indexed through deduped targeted refreshes off the UI thread.
- Rust and Python expose paged detail, global search, and batched summary contracts.
- Existing `artifact_show`, `artifact_list`, and CLI behavior remain backward compatible.
- High-degree artifacts can be handled without local all-row slicing in the future modal.
- `just check` passes after the final phase.
