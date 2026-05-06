---
legend: sdd/legends/202605/artifacts_panel_redesign.md
epic: 6
title: Artifacts Panel Redesign Epic 6 Performance Documentation And Rollout
bead_id: sase-24.6
tier: epic
legend_bead_id: sase-24
create_time: 2026-05-06 01:53:10
status: done
prompt: sdd/prompts/202605/artifacts_panel_epic6_rollout.md
---

# Artifacts Panel Redesign Epic 6 Plan

## Objective

Implement Epic 6, "Performance, Documentation, And Rollout", from `sdd/legends/202605/artifacts_panel_redesign.md`.

Epic 6 should close the artifacts panel redesign with evidence, guardrails, and operator-facing documentation. It should
not introduce a new product surface unless validation uncovers a contract bug. The main output is a reliable quality
gate for the work delivered by Epics 1-5:

- `sase ace` startup stays near the old ~1s target and does not run broad unified artifact graph rebuilds or source
  scans before first paint.
- Newly-created artifacts remain indexed by bounded targeted refresh paths.
- Existing users have a documented explicit sync/rebuild path for historical artifacts.
- Backend semantics, Python wire contracts, CLI behavior, Textual modal behavior, and CL/Agent indicators are all
  covered by focused tests.
- The checked-in benchmark harness can measure the user-visible paths called out by the legend.
- `just check` passes after `just install` in this workspace, and any touched Rust core work is validated in
  `../sase-core`.

## Current Context

The previous epic plans show the intended dependency chain:

- Epic 1 (`sdd/epics/202605/artifacts_panel_epic1.md`) made file type semantics, sparse directory artifacts, and
  `sase artifact sync` the migration contract.
- Epic 2 (`sdd/epics/202605/artifact_epic2_fast_indexing_query_contracts.md`) added startup/indexing guardrails,
  `artifact_show_paged`, `artifact_search`, and `artifact_summary`.
- Epic 3 (`sdd/epics/202605/artifact_epic3_relationship_navigator.md`) redesigned the modal around paged detail,
  per-group paging, global search, and apostrophe row navigation.
- Epic 4 (`sdd/epics/202605/artifacts_panel_epic4_indicators.md`) planned CL/Agent artifact indicators and is still
  marked `wip` in the plan file at the time this Epic 6 plan was written.
- Epic 5 (`sdd/epics/202605/artifacts_panel_epic5.md`) planned right-pane detail renderer, missing-state, and
  reliability polish.

Relevant existing code and tests already present in this checkout include:

- Rust artifact contracts in `../sase-core/crates/sase_core/src/artifact/` and PyO3 bindings in
  `../sase-core/crates/sase_core_py/src/lib.rs`.
- Python facade and wire records in `src/sase/core/artifact_facade.py` and `src/sase/core/artifact_wire/`.
- Artifact CLI and docs in `src/sase/main/artifact_cli/`, `src/sase/main/parser_artifact.py`, `docs/artifacts.md`, and
  `src/sase/xprompts/skills/sase_artifact.md`.
- Artifact modal code and renderer tests under `src/sase/ace/tui/modals/` and `tests/ace/tui/modals/`.
- CL/Agent indicator model and wiring under `src/sase/ace/tui/models/artifact_indicator.py`,
  `src/sase/ace/tui/models/artifact_summary_cache.py`, `src/sase/ace/tui/actions/artifact_summaries.py`, and list widget
  tests.
- Current artifact perf harness under `tests/perf/artifact_graph/` and `tests/perf/bench_artifact_graph.py`.

One known drift to check early: `tests/perf/artifact_graph/modal_measurements.py` still builds a fake modal around the
legacy `show_func` compatibility path. Epic 6 should move benchmark coverage onto the default paged modal path, while
keeping legacy compatibility tests where they belong.

## Non-Goals

- Do not add automatic historical sync/rebuild to `sase ace` startup, modal open, search, indicators, or
  missing-artifact states.
- Do not replace the existing `~/.sase/agent_artifact_index.sqlite` startup compatibility path.
- Do not redesign the modal, CL rows, or Agent rows beyond fixes required to satisfy the landed contracts.
- Do not broaden benchmark scripts into a hard workstation latency gate unless there is already a stable local threshold
  policy. Correctness and boundedness should gate tests; latency numbers should be recorded for rollout evidence.
- Do not add runtime-specific behavior for Claude, Gemini, Codex, or other providers.

## Phase 6.1: Contract Audit And Baseline Inventory

Goal: establish the exact landed state before later agents add tests, benchmarks, or docs.

Primary ownership:

- `sdd/epics/202605/artifacts_panel_epic1.md`
- `sdd/epics/202605/artifact_epic2_fast_indexing_query_contracts.md`
- `sdd/epics/202605/artifact_epic3_relationship_navigator.md`
- `sdd/epics/202605/artifacts_panel_epic4_indicators.md`
- `sdd/epics/202605/artifacts_panel_epic5.md`
- Existing tests under `tests/ace/tui/`, `tests/main/`, `tests/test_core_facade/`, and `tests/perf/artifact_graph/`
- Optional short audit note under `sdd/tales/202605/` if the agent finds material drift

Implementation shape:

1. Confirm whether all prior epic phase beads are landed, especially Epic 4. If any prior phase is still open, record
   Epic 6 as blocked on that phase instead of duplicating its implementation.
2. Build a traceability matrix from legend acceptance criteria to existing tests:
   - startup no broad artifact calls
   - targeted new artifact indexing
   - manual historical sync/rebuild
   - directory invariant
   - canonical file type taxonomy
   - paged one-line navigator rows
   - persistent header
   - local `/` filter versus global `S` search
   - apostrophe row navigation
   - CL/Agent artifact indicators without hot-path summary queries
3. Identify stale tests or benchmarks that still exercise legacy behavior as the primary path.
4. Identify missing validation across Rust core, PyO3/Python facade, CLI, Textual modal, CL/Agent indicators, docs, and
   performance harnesses.
5. Make only small test-name or note updates if needed. Do not make broad product code changes in the audit phase.

Acceptance checks:

- The agent leaves a concrete list of missing or stale coverage for Phases 6.2-6.5.
- Any blocker from prior epics is called out explicitly with file/test references.
- No production behavior changes are made unless they are tiny fixes needed to keep existing tests meaningful.

Suggested verification:

```bash
just install
pytest tests/perf/bench_artifact_graph.py -q
pytest tests/ace/tui/modals/test_artifact_panel_modal.py \
  tests/ace/tui/modals/test_artifact_panel_paging_search.py \
  tests/ace/tui/modals/test_artifact_panel_jump.py \
  tests/ace/tui/modals/test_artifact_panel_states.py -q
```

## Phase 6.2: Performance Measurement Harness

Goal: make the checked-in benchmark harness measure the legend's rollout scenarios with bounded, realistic paths.

Primary ownership:

- `tests/perf/bench_artifact_graph.py`
- `tests/perf/artifact_graph/startup_measurements.py`
- `tests/perf/artifact_graph/modal_measurements.py`
- `tests/perf/artifact_graph/fixture_measurements.py`
- `tests/perf/artifact_graph/benchmark.py`
- `tests/perf/artifact_graph/records.py`
- Perf README or benchmark usage notes if present

Implementation shape:

1. Keep the startup sentinel that asserts zero broad calls to `artifact_rebuild`, `artifact_list`, `artifact_show`,
   `artifact_show_paged`, `artifact_search`, and `artifact_summary` during startup scheduling.
2. Add or update measurements for the exact Epic 6 matrix:
   - cold-ish startup scheduling to first paint boundary
   - startup with missing unified artifact index
   - panel open on an existing artifact through the default `artifact_show_paged` path
   - panel open on a missing artifact requiring one targeted refresh
   - global search with explicit limit
   - high-degree artifact navigation with 200+ links and per-group page size 10
   - batched CL/Agent visible-row summary query
3. Replace modal benchmark reliance on `show_func` as the primary measurement. Use `show_paged_func` or the
   facade-backed default paged path, and keep a separate compatibility assertion if needed.
4. Record query/mutation counts in benchmark records so tests can assert boundedness without relying on exact latency.
5. Keep latency output descriptive. If writing a JSON artifact is supported, document the command:
   `python tests/perf/bench_artifact_graph.py --runs 3 --output /tmp/artifacts-panel-epic6.json`.
6. Ensure the harness does not read or mutate real user artifact indexes; use temporary indexes and deterministic
   fixtures.

Acceptance checks:

- `test_artifact_graph_benchmark_smoke` fails if modal open uses the legacy all-detail path or performs unbounded row
  loading.
- Missing-index startup and missing-artifact modal cases do not run broad sync/rebuild.
- High-degree and search measurements honor explicit limits.
- Benchmark output includes enough data for the final rollout note: latency summary, query counts, mutation counts,
  fixture sizes, and errors.

Suggested verification:

```bash
pytest tests/perf/bench_artifact_graph.py -q
python tests/perf/bench_artifact_graph.py --runs 1 --projects 2 --beads 4 --agents 4 --modal-linked 240
```

## Phase 6.3: Backend, Facade, And CLI Test Matrix

Goal: close semantic and wire-contract gaps below the TUI.

Primary ownership:

- Rust core tests in `../sase-core/crates/sase_core/src/artifact/`
- PyO3 binding tests in `../sase-core/crates/sase_core_py/src/lib.rs`
- Python wire/facade tests under `tests/test_core_facade/`
- CLI tests under `tests/main/test_artifact_cli_*.py`
- CLI parser/handler/help files only for focused fixes:
  - `src/sase/main/parser_artifact.py`
  - `src/sase/main/artifact_handler.py`
  - `src/sase/main/artifact_cli/`

Implementation shape:

1. Ensure Rust tests cover:
   - file types `plan`, `diff`, `chat`, `project`, `prompt`, `misc`
   - missing/unknown file artifact metadata reading as `misc`
   - file type SQL/cache filtering
   - sparse directory invariant and `orphan_directory` doctor diagnostics
   - `artifact_show_paged` counts/pages and high-degree behavior
   - `artifact_search` text/kind/file-type limit/offset ordering
   - `artifact_summary` batched semantics and no parent-containment inflation
2. Ensure PyO3/Python tests cover:
   - new wire records and schema conversions
   - `artifact_show_paged`, `artifact_search`, and `artifact_summary` real-extension availability
   - old file rows without `metadata.artifact_type`
3. Ensure CLI tests cover:
   - `sase artifact sync` as explicit rebuild alias
   - `list/search -F/--file-type`
   - help text for manual sync/rebuild and no automatic startup sync
   - JSON output shapes for list/search/show/doctor remain stable
4. Fix product code only where a test exposes a real contract violation. Shared backend behavior belongs in
   `../sase-core`; Python remains a thin adapter.

Acceptance checks:

- Backend and CLI coverage can be run independently by a future agent.
- No startup, modal, or row-render path calls broad rebuild/sync as a side effect of a facade or CLI helper.
- CLI short options remain present for all new options.

Suggested verification:

```bash
(cd ../sase-core && cargo test -p sase_core artifact)
(cd ../sase-core && cargo test -p sase_core_py artifact)
pytest tests/test_core_facade/test_artifact.py \
  tests/test_core_facade/test_artifact_wire.py \
  tests/test_core_facade/test_artifact_facade_bindings.py \
  tests/main/test_artifact_cli_parser.py \
  tests/main/test_artifact_cli_read_commands.py \
  tests/main/test_artifact_cli_maintenance_commands.py \
  tests/main/test_artifact_cli_real_extension.py \
  tests/main/test_artifact_cli_real_extension_sync.py -q
```

## Phase 6.4: TUI Modal, Indicators, And Hot-Path Regression Gate

Goal: make the Textual UI contracts hard to regress without expanding implementation scope.

Primary ownership:

- Modal code/tests:
  - `src/sase/ace/tui/modals/artifact_panel_modal.py`
  - `src/sase/ace/tui/modals/artifact_panel_state*.py`
  - `src/sase/ace/tui/modals/artifact_panel_renderers/`
  - `tests/ace/tui/modals/test_artifact_panel_*.py`
- Indicator code/tests:
  - `src/sase/ace/tui/models/artifact_indicator.py`
  - `src/sase/ace/tui/models/artifact_summary_cache.py`
  - `src/sase/ace/tui/actions/artifact_summaries.py`
  - CL/Agent list widget files under `src/sase/ace/tui/widgets/`
  - CL/Agent display actions under `src/sase/ace/tui/actions/`
  - indicator tests under `tests/ace/tui/`
- Startup/hot-path sentinels:
  - `tests/ace/tui/actions/test_agent_artifact_startup_contracts.py`
  - `tests/ace/tui/test_artifact_graph_refresh.py`
  - `tests/ace/tui/test_agent_artifact_indicators.py`

Implementation shape:

1. Add or tighten tests for modal acceptance:
   - persistent header and context strip
   - one-line rows with badges and counted groups
   - per-group `show more` paging
   - `/` local filter without global search calls
   - `S` global search through bounded `artifact_search`
   - apostrophe jump mode for relationship rows, show-more rows, and search rows
   - missing artifact after targeted refresh shows manual command guidance
   - SQLite busy/search/load errors are recoverable
   - stale workers cannot overwrite newer loads or graph preview/export
2. Add or tighten tests for CL/Agent indicators:
   - shared renderer semantics are identical
   - one batched `artifact_summary` per list refresh
   - zero summary queries during startup and repeated j/k navigation
   - row/cache signatures include indicator changes
   - grouped CL and multi-panel Agent layouts remain single-line and patchable
3. Monkeypatch broad graph calls in hot-path tests and fail if they occur.
4. Keep visual/style fixes restrained and tied to failing tests or clear overlap/truncation issues.

Acceptance checks:

- Modal and indicator tests cover every user-facing artifact-panel acceptance bullet from the legend.
- Hot navigation remains query-free for artifact graph summaries and broad graph operations.
- No broad historical sync/rebuild is callable from missing-state rendering or indicator loading.

Suggested verification:

```bash
pytest tests/ace/tui/modals/test_artifact_panel_modal.py \
  tests/ace/tui/modals/test_artifact_panel_paging_search.py \
  tests/ace/tui/modals/test_artifact_panel_jump.py \
  tests/ace/tui/modals/test_artifact_panel_renderers.py \
  tests/ace/tui/modals/test_artifact_panel_rows.py \
  tests/ace/tui/modals/test_artifact_panel_states.py \
  tests/ace/tui/test_artifact_panel_launch.py \
  tests/ace/tui/test_artifact_graph_refresh.py \
  tests/ace/tui/test_agent_artifact_indicators.py \
  tests/ace/tui/actions/test_artifact_summary_loading.py \
  tests/ace/tui/widgets/test_agent_display.py \
  tests/ace/tui/widgets/test_changespec_list_grouped.py -q
```

## Phase 6.5: Documentation, Skill Text, And Rollout Notes

Goal: make the final model clear for users and future agents.

Primary ownership:

- `docs/artifacts.md`
- `src/sase/xprompts/skills/sase_artifact.md`
- CLI help text in `src/sase/main/parser_artifact.py` and `src/sase/main/artifact_cli/` if gaps remain
- New SDD tale under `sdd/tales/202605/`

Implementation shape:

1. Update documentation and skill text to cover the final model:
   - directory invariant: only `/` or directories containing visible non-directory artifacts
   - file type taxonomy: `plan`, `diff`, `chat`, `project`, `prompt`, `misc`
   - manual historical sync/backfill: `sase artifact sync` / `sase artifact rebuild`
   - startup policy: no broad sync/rebuild on `sase ace` startup
   - newly-created artifact policy: bounded targeted refresh where SASE observes changed sources
   - artifact panel keymap summary: `A`, `/`, `S`, apostrophe, `g`, `G`, back/forward/root/parent where documented
   - CL/Agent indicators and what the compact counts mean
2. Ensure docs do not imply the modal or startup will repair historical indexes automatically.
3. Add a concise SDD tale such as `sdd/tales/202605/artifacts_panel_epic6_rollout.md` with:
   - what shipped across Epics 1-6
   - benchmark command and representative local results if Phase 6.2 produced them
   - remaining operational caveats
   - rollback/mitigation: run manual sync, disable reliance on stale index by rebuilding, and inspect doctor output
4. Keep generated skill wording aligned with CLI behavior. If there is a skill generation pipeline requirement, follow
   `memory/long/generated_skills.md` before editing generated sources.

Acceptance checks:

- User-facing docs and `/sase_artifact` skill agree on commands and policy.
- The final SDD tale is specific enough for a future agent to understand what was validated.
- CLI help, docs, and tests agree on `sync`, `rebuild`, `search`, and `--file-type` wording.

Suggested verification:

```bash
pytest tests/main/test_artifact_cli_parser.py tests/main/test_artifact_cli_read_commands.py \
  tests/main/test_artifact_cli_maintenance_commands.py -q
rg -n "artifact sync|artifact rebuild|artifact_type|apostrophe|global search|sase ace startup" \
  docs/artifacts.md src/sase/xprompts/skills/sase_artifact.md sdd/tales/202605
```

## Phase 6.6: Final Integration And Release Gate

Goal: integrate prior phase fixes, run the full gate, and leave the epic ready to land.

Primary ownership:

- Cross-cutting fixes only where earlier Epic 6 phases expose conflicts
- `sdd/tales/202605/artifacts_panel_epic6_rollout.md`
- Any checked-in benchmark output location only if the repo already has a convention for perf artifacts

Implementation shape:

1. Re-run the traceability matrix from Phase 6.1 and mark each legend acceptance criterion covered by either tests,
   benchmark records, docs, or an explicit handoff note.
2. Run focused suites from Phases 6.2-6.5 first and fix integration failures.
3. Run Rust checks if any sibling Rust files were touched during Epic 6:
   - `cargo test -p sase_core artifact`
   - `cargo test -p sase_core_py artifact`
4. Run repository validation:
   - `just install`
   - `just check`
5. Run the benchmark script with at least one smoke run and record the command, fixture size, boundedness result, and
   representative timings in the SDD tale. Do not fail the epic solely on local latency unless it reveals an obvious
   regression or unbounded call pattern.
6. Confirm the final diff does not add broad sync/rebuild calls to startup, modal open, search, missing-state display,
   CL/Agent indicator loading, or hot j/k navigation.

Acceptance checks:

- `just check` passes in this repo.
- Relevant Rust cargo tests pass if Rust was touched.
- Benchmark smoke passes and emits no correctness/boundedness errors.
- The SDD tale links the final gate back to Epic 6 and lists any residual risks.
- The final agent handoff includes changed files, commands run, benchmark output location if any, and remaining risks.

Suggested verification:

```bash
just install
pytest tests/perf/bench_artifact_graph.py -q
python tests/perf/bench_artifact_graph.py --runs 1 --projects 2 --beads 4 --agents 4 --modal-linked 240
just check
```

## Phase Dependencies And Agent Boundaries

Recommended order:

1. Phase 6.1 first. It is the only phase that should decide whether Epic 6 is blocked by unfinished prior epic work.
2. Phase 6.2 can start after Phase 6.1 because it relies on knowing which benchmark paths are stale.
3. Phases 6.3 and 6.4 can run in parallel after Phase 6.1 if they keep their write scopes separate:
   - Phase 6.3 owns Rust/Python facade/CLI contract tests.
   - Phase 6.4 owns Textual modal, indicator, startup, and hot-path tests.
4. Phase 6.5 should start after Phase 6.1 and preferably after Phases 6.3/6.4 identify any wording changes. It should
   avoid touching benchmark or modal tests unless docs tests require it.
5. Phase 6.6 lands last after all other phases.

Avoid overlapping write scopes:

- Phase 6.2 owns `tests/perf/artifact_graph/` and `tests/perf/bench_artifact_graph.py`.
- Phase 6.3 owns backend/facade/CLI tests and only focused product fixes below the TUI.
- Phase 6.4 owns TUI modal/indicator tests and only focused product fixes in TUI code.
- Phase 6.5 owns docs, skill text, CLI help wording, and the rollout tale.
- Phase 6.6 may touch any file, but only for integration fixes after previous phases land.

## Risks And Mitigations

- Risk: Epic 4 is not fully landed when Epic 6 begins. Mitigation: Phase 6.1 treats prior open work as a blocker rather
  than reimplementing indicators inside the quality-gate epic.
- Risk: performance work becomes flaky due to local machine timing. Mitigation: gate boundedness, call counts, and
  fixture correctness; record timings descriptively.
- Risk: benchmark fixtures accidentally touch real user indexes. Mitigation: all benchmark paths must use temp indexes
  and patched homes.
- Risk: tests assert legacy modal paths as primary behavior. Mitigation: move perf and product tests to
  `artifact_show_paged`; keep `show_func` only as a compatibility injection test.
- Risk: docs promise automatic repair. Mitigation: keep manual `sync`/`rebuild` wording explicit and test CLI help.
- Risk: cross-repo changes are missed by `just check`. Mitigation: any phase touching `../sase-core` must run the
  relevant cargo tests and report them.

## Final Outcome

After Epic 6, the artifacts panel redesign should be ready for normal use and future development:

- Startup, search, modal open, targeted refresh, high-degree navigation, and summary indicators have a checked-in
  boundedness/performance smoke harness.
- Backend semantics, Python wire contracts, CLI behavior, modal behavior, and CL/Agent indicators have explicit tests.
- Operators know when to run `sase artifact sync` or `sase artifact rebuild`, and they know `sase ace` will not run that
  historical sync for them.
- Future agents have a rollout tale and docs that describe the final model without reverse-engineering prior epics.
