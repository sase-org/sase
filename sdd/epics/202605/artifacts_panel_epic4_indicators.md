---
create_time: 2026-05-05 23:52:18
status: wip
prompt: sdd/prompts/202605/artifacts_panel_epic4_indicators.md
bead_id: sase-24.4
tier: epic
legend_bead_id: sase-24
---
# Plan: Artifacts Panel Redesign Epic 4 - CLs And Agents Artifact Indicators

## Objective

Implement Epic 4 from `sdd/legends/202605/artifacts_panel_redesign.md`: CLs and Agents rows should show compact,
consistent artifact-availability indicators before the user opens the artifacts panel.

The implementation must preserve the existing fast navigation model:

- No `artifact_summary` or other unified artifact graph calls during `sase ace` startup.
- No artifact summary queries in hot j/k paths.
- Summary loading happens once per CL list refresh and once per Agent list refresh, batched by visible artifact IDs.
- Missing or unsynced artifact index states must be quiet: render nothing or a dim `art ?`, and never trigger rebuilds.
- Rendering semantics must be identical across CL and Agent rows.

## Current Context

Relevant existing pieces:

- Python facade already exposes
  `sase.core.artifact_facade.artifact_summary(index_path, ArtifactSummaryRequestWire(...))`.
- Rust core already implements a batched `artifact_summary` query that excludes parent containment links and counts
  immediate non-parent neighbors by file type and non-file kind.
- TUI state already initializes `ArtifactSummaryCache` in `src/sase/ace/tui/actions/_state_init.py`.
- Artifact graph refresh events already invalidate that cache in `src/sase/ace/tui/actions/event_handlers.py`.
- CL row rendering lives in:
  - `src/sase/ace/tui/widgets/_changespec_list_helpers.py`
  - `src/sase/ace/tui/widgets/_changespec_list_render.py`
  - `src/sase/ace/tui/widgets/changespec_list.py`
- Agent row rendering lives in:
  - `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
  - `src/sase/ace/tui/widgets/_agent_list_render_cache.py`
  - `src/sase/ace/tui/widgets/_agent_list_build.py`
  - `src/sase/ace/tui/widgets/agent_list.py`
  - `src/sase/ace/tui/actions/agents/_display_panels.py`
- The startup sentinel already patches `artifact_summary` as a forbidden startup call in
  `tests/perf/artifact_graph/startup_measurements.py`.

## Phase 1: Shared Indicator Model And Renderer

Owner scope:

- Add a shared TUI-side artifact indicator module, likely `src/sase/ace/tui/models/artifact_indicator.py` or
  `src/sase/ace/tui/widgets/artifact_indicator.py`.
- Extend or wrap `ArtifactSummaryCache` only as needed for UI state access.
- Add focused unit tests, likely under `tests/ace/tui/models/` or `tests/ace/tui/widgets/`.

Implementation requirements:

- Define a small Python value object for row indicators with:
  - `artifact_id`
  - `state`: ok, missing, loading, stale, error
  - `total_count`
  - per file-type counts for `plan`, `diff`, `chat`, `project`, `prompt`, `misc`
  - optional non-file kind counts for `agent`, `bead`, `thought`, `commit`, `changespec`, etc.
  - optional `error`
- Convert from `ArtifactSummaryWire` into that value object.
- Preserve canonical ordering:
  - file types: `plan`, `diff`, `chat`, `project`, `prompt`, `misc`
  - non-file kinds after file types, using a stable explicit order for common kinds and lexical fallback for unknowns.
- Add a shared Rich `Text` renderer used by both CL and Agent rows.
- Keep output compact. Target examples:
  - no linked artifacts: render empty
  - ok summary: `art 8 plan2 diff1 chat3 misc2`
  - missing/loading useful state: dim `art ?`
  - error state: dim or warning-styled `art !`
- The renderer should be deterministic and width-measurable without widget state.

Phase 1 acceptance:

- Unit tests cover ordering, zero-count suppression, missing/loading/error output, non-file counts, and identical output
  for CL/Agent callers.
- No CL or Agent list integration in this phase except imports allowed for tests.
- No artifact facade calls in this phase.

## Phase 2: Batched Summary Loading And Cache Semantics

Owner scope:

- Add shared loader orchestration in TUI actions/models. Good candidates:
  - `src/sase/ace/tui/models/artifact_summary_cache.py`
  - a new helper under `src/sase/ace/tui/actions/artifact_summaries.py`
  - minimal hooks in `src/sase/ace/tui/actions/changespec/_loading.py`
  - minimal hooks in `src/sase/ace/tui/actions/agents/_loading.py` or `_loading_finalize.py`
- Do not modify row renderers beyond temporary plumbing tests if avoidable.

Implementation requirements:

- Provide a single helper that accepts visible artifact IDs, reads the existing cache, and batches missing IDs into one
  `artifact_summary` call.
- Use `default_artifact_index_path()` from artifact graph refresh/facade conventions rather than inventing paths.
- Handle missing index/backend errors without rebuilding:
  - mark requested IDs as error/missing/loading-complete state in cache, or expose an app-level "unavailable" state.
  - do not notify noisily during normal row rendering.
- Ensure CL list refresh requests summaries for visible `ChangeSpec.name` artifact IDs.
- Ensure Agent list refresh requests summaries for visible stable agent artifact IDs:
  - named agent: `agent.agent_name`
  - legacy fallback should match `ArtifactsMixin` fallback ID behavior, not invent a second ID scheme.
- Cache summaries beside existing list-render state and invalidate only via existing artifact graph refresh
  invalidation.
- Loader must run on list refresh/reload paths, not selection movement.

Phase 2 acceptance:

- Tests prove one batched facade call per CL refresh and one per Agent refresh when IDs are missing.
- Tests prove cached summaries suppress duplicate calls on repeated renders with the same cache version.
- Tests prove index/facade failures do not call rebuild/sync and do not crash display refresh.
- Existing startup sentinel continues to show no `artifact_summary` calls during startup scheduling.
- No visible row indicator integration required yet beyond exposing data to later phases.

## Phase 3: CLs Tab Row Integration

Owner scope:

- `src/sase/ace/tui/actions/changespec/_display.py`
- `src/sase/ace/tui/widgets/changespec_list.py`
- `src/sase/ace/tui/widgets/_changespec_list_helpers.py`
- `src/sase/ace/tui/widgets/_changespec_list_render.py`
- CL widget tests under `tests/ace/tui/widgets/` and display tests under `tests/ace/tui/`.

Implementation requirements:

- Thread optional artifact indicators through `ChangeSpecList.update_list()`, `format_changespec_option()`,
  `calculate_entry_display_width()`, and `row_signature()`.
- Use the shared renderer from Phase 1.
- Keep indicator placement compact and subordinate to status/name/CL/mentor stats.
- Width calculation must include the indicator so `WidthChanged` remains accurate.
- Patch path must include indicator in row signatures and patch rendering so stale indicators do not persist.
- Grouped CL rendering and banner rows must remain unaffected.
- Jump hints, marked rows, mentor stats, hidden/submitted indicators, and status prefixes must still fit in one line.

Phase 3 acceptance:

- Unit/widget tests prove CL rows render artifact indicators with the same shared text semantics.
- Tests cover width growth and row patch fallback when an indicator no longer fits cached width.
- Tests cover grouped CL lists with banner rows.
- Tests prove CL j/k detail-only refresh does not call summary loading or `ChangeSpecList.update_list()`.

## Phase 4: Agents Tab Row Integration

Owner scope:

- `src/sase/ace/tui/actions/agents/_display.py`
- `src/sase/ace/tui/actions/agents/_display_panels.py`
- `src/sase/ace/tui/widgets/agent_list.py`
- `src/sase/ace/tui/widgets/_agent_list_build.py`
- `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
- `src/sase/ace/tui/widgets/_agent_list_render_cache.py`
- Agent widget/display tests under `tests/ace/tui/widgets/` and `tests/ace/tui/`.

Implementation requirements:

- Thread optional artifact indicators through `AgentList.update_list()`, panel slicing, and `format_agent_option()`.
- Add indicator input to `agent_render_key()` so cached rows invalidate when summaries change.
- Keep workflow child rows readable:
  - indicator should not crowd step counters, runtime suffixes, bead IDs, tags, or agent-name annotations.
  - prefer placing the indicator near other secondary badges before the right-aligned runtime suffix.
- Preserve panel width calculations and dynamic panel heights.
- Preserve single-row patch behavior:
  - patch path must see the current indicator for the local row.
  - cache invalidation must not flush unrelated panels unless necessary.
- Use the same renderer and ordering as CL rows.

Phase 4 acceptance:

- Unit/widget tests prove Agent rows render the same indicator text and styles as CL rows.
- Tests prove render cache keys include indicator changes.
- Tests cover workflow parents and workflow child rows.
- Tests cover tag-driven multi-panel display.
- Tests prove agent j/k highlight-only refresh does not call summary loading or rebuild panel widgets.

## Phase 5: Refresh Wiring, Performance Regression Tests, And Polish

Owner scope:

- Cross-cutting tests and small fixes across Phase 2-4 files.
- Perf/startup sentinels under `tests/perf/artifact_graph/`.
- Existing row/navigation regression tests under `tests/ace/tui/`.

Implementation requirements:

- Ensure list-refresh orchestration loads summaries before or alongside row render in a deterministic way:
  - if async load completes after an initial render, schedule one list refresh that uses cache data.
  - avoid infinite refresh loops on error/missing states.
- Confirm artifact graph refresh invalidation causes the next CL/Agent list refresh to reload summaries.
- Confirm hot navigation remains clean:
  - CL `_refresh_changespecs_display_debounced()` must not load summaries.
  - Agent `_refresh_agents_display_debounced()` and `_refresh_panel_highlights()` must not load summaries.
- Add regression tests that monkeypatch `artifact_summary` and assert:
  - startup scheduling: zero calls
  - CL list full refresh: one batched call
  - Agent list full refresh: one batched call
  - 50 j/k selections: zero calls
- Review styling in both tabs for compactness and visual consistency.

Phase 5 acceptance:

- `just install` has been run in the workspace before tests.
- Focused tests from all phases pass.
- `just check` passes in this repo.
- If Rust core is touched, the implementing agent must also run the relevant sibling `../sase-core` checks and document
  them in its handoff.

## Phase Dependencies And Agent Boundaries

Recommended order:

1. Phase 1 first. It creates the shared model/renderer and should not depend on app lifecycle.
2. Phase 2 second. It provides cached data to row renderers without changing row layout yet.
3. Phases 3 and 4 can run in parallel after Phases 1 and 2 if their write scopes stay separate.
4. Phase 5 lands last and should integrate any small mismatches from Phases 3 and 4.

Avoid overlapping write scopes:

- Phase 3 owns CL row files.
- Phase 4 owns Agent row files.
- Phase 2 owns loader/cache orchestration.
- Phase 5 may touch all files, but only for integration fixes and tests after previous phases land.

## Risks And Mitigations

- Risk: artifact IDs for legacy unnamed agents drift from the panel-open behavior. Mitigation: reuse the same
  artifact-id helper or extract one from `ArtifactsMixin` before wiring summary loads.
- Risk: render caches show stale indicators. Mitigation: include indicator summaries or a compact indicator signature in
  row signatures/cache keys.
- Risk: summary loading sneaks into hot navigation. Mitigation: centralize loading in list refresh/reload paths and add
  monkeypatch tests around j/k paths.
- Risk: missing indexes make row rendering noisy or slow. Mitigation: catch facade errors in the loader, cache
  unavailable states, render dim output, and never rebuild.
- Risk: indicators make rows too wide. Mitigation: deterministic width calculation, compact count labels, and patch
  fallback when width grows beyond cached target.

## Non-Goals

- Do not change Rust artifact summary semantics unless tests reveal a contract bug.
- Do not run `sase artifact sync` or `artifact_rebuild` from `sase ace`.
- Do not add per-row `artifact_show` calls.
- Do not redesign the artifacts modal in this epic.
- Do not replace the existing `agent_artifact_index.sqlite` startup path.

## Final Verification

At the end of the last phase:

```bash
just install
just check
```

Expected outcome: CLs and Agents tabs show consistent compact artifact indicators grouped by type, backed by one batched
summary query per list refresh and zero artifact queries in startup/hot-navigation paths.
