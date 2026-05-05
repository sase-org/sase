---
legend: sdd/legends/202605/unified_artifacts.md
epic: 6
title: Unified Artifacts Epic 6 End-To-End Quality Gate
tier: epic
bead_id: sase-23.6
legend_bead_id: sase-23
status: wip
create_time: 2026-05-05 15:26:26
prompt: sdd/prompts/202605/unified_artifacts_epic6_quality_gate.md
---

# Unified Artifacts Epic 6 Plan

## Scope

Implement Epic 6, "End-To-End Quality Gate", from `sdd/legends/202605/unified_artifacts.md`.

This is a hardening and verification epic. The unified artifact graph already has implementation surfaces in this
checkout:

- Rust graph storage, query, export, ingestion, and wire records under `../sase-core/crates/sase_core/src/artifact/`.
- PyO3 bindings under `../sase-core/crates/sase_core_py/src/lib.rs`.
- Python wire/facade adapters under `src/sase/core/artifact_wire/` and `src/sase/core/artifact_facade.py`.
- CLI parser/handler under `src/sase/main/parser_artifact.py` and `src/sase/main/artifact_handler.py`.
- TUI artifact panel under `src/sase/ace/tui/modals/artifact_panel_*`, `src/sase/ace/tui/actions/artifacts.py`, and
  refresh wiring in `src/sase/ace/tui/artifact_graph_refresh.py`.
- Docs and skill source in `docs/artifacts.md` and `src/sase/xprompts/skills/sase_artifact.md`.

Epic 6 should add missing coverage, fix defects discovered by that coverage, and leave an explicit quality gate that
future artifact graph changes can run. It should not redesign the artifact graph or add new product behavior unless a
test exposes a blocker in the existing contract.

The work crosses the Rust/Python boundary. Shared graph behavior and ingestion correctness belong in
`../sase-core/crates/sase_core`; Python should own facade conversion, CLI formatting, TUI behavior, and thin
binding-adapter tests.

## Product Contract

After Epic 6:

- Rust graph primitives are covered by deterministic tests for mutation, tombstone, traversal, query ordering, doctor
  diagnostics, and bounded exports.
- Rust ingestion fixtures cover project files, archive project files, ChangeSpecs, commits, directories, beads, agents,
  created files, worker links, retry/follow-up links, thoughts, stale cleanup, and mixed end-to-end rebuilds.
- PyO3 bindings prove every exposed artifact command round-trips JSON-compatible wire shapes and rejects invalid request
  shapes predictably.
- Python facade and CLI tests cover every `sase artifact` subcommand in JSON and human output modes, including error
  paths and short-option coverage.
- TUI tests prove `A` opens the artifact panel from AXE, CLs, and Agents, normal row movement does not requery or
  rebuild, graph preview/export is explicit and bounded, and renderers handle missing or partial payloads.
- Integrated checks run in the right order:
  - in `../sase-core`: `cargo test`
  - in this repo: `just install` then `just check`
- Targeted performance measurements document graph rebuild, targeted upsert, and modal open latency with deterministic
  local fixtures.

## Non-Goals

- Do not rework the schema, link types, or artifact IDs except to fix a contract violation exposed by tests.
- Do not remove legacy compatibility surfaces in this epic.
- Do not make tests depend on the user's real `~/.sase` state. Use tempdirs and synthetic fixtures.
- Do not introduce runtime-specific branches for Claude, Gemini, Codex, or plugin providers. Test provider differences
  through shared metadata shapes.
- Do not hand-edit generated skill output. If skill source changes become necessary, run the normal generation workflow
  in the same phase.

## Phase Breakdown

Each phase below is intended for a distinct implementation agent instance. Later phases should treat earlier tests and
fixtures as committed contracts. If a phase discovers a real bug, that agent should fix the smallest affected
implementation surface and keep the regression test in the same phase.

Every phase that edits this repo must start with `just install` in this workspace before running project commands. Every
phase that edits this repo must finish with `just check`. Rust-touching phases must also run focused `cargo test` in
`../sase-core`, and the final phase must run the full integrated gate.

## Phase 6.1: Rust Graph Primitive Coverage

Goal: make the Rust artifact store/query/export layer independently trustworthy.

Dependencies: completed Epic 1 implementation.

Primary ownership:

- `../sase-core/crates/sase_core/src/artifact/store.rs`
- `../sase-core/crates/sase_core/src/artifact/query.rs`
- `../sase-core/crates/sase_core/src/artifact/export.rs`
- `../sase-core/crates/sase_core/src/artifact/wire.rs`
- Rust unit tests colocated in those modules or focused integration tests under `../sase-core/crates/sase_core/tests/`

Implementation shape:

- Inventory existing artifact primitive tests and add only missing coverage.
- Cover node upsert semantics:
  - root invariant
  - insert vs update counts
  - duplicate IDs
  - provenance/source metadata preservation
  - payload upsert and replacement behavior
- Cover link semantics:
  - directed `parent`, `created`, `worker`, and `related` links
  - duplicate link upserts
  - dangling source/target diagnostics
  - reverse-parent child lookup
- Cover removals and tombstones:
  - manual removal
  - derived tombstone suppression
  - tombstoned rows excluded by default and included on request
  - derived row resurrection behavior after tombstone removal, if supported
- Cover queries:
  - kind, link type, provenance, source kind/id, text, root reachability, limit, offset, and deterministic ordering
  - path-to-root for connected nodes, root, missing nodes, and cycles
- Cover doctor/export:
  - unreachable nodes
  - dangling links
  - duplicate/conflicting derived data where the implementation can detect it
  - DOT, Mermaid, JSON, and text export determinism and bounding

Acceptance checks:

- Focused Rust tests fail if `parent` directionality is inverted.
- Doctor tests distinguish errors from warnings where the current wire contract supports severity.
- Export tests verify stable output ordering across repeated runs.
- No Python or TUI code is required for this phase unless a binding contract bug is exposed.

Suggested verification:

- In `../sase-core`: `cargo test -p sase_core artifact::store artifact::query artifact::export artifact::wire`.
- If module filtering is insufficient: `cargo test -p sase_core artifact`.

## Phase 6.2: Rust Ingestion Fixture Coverage

Goal: prove rebuild and targeted upsert construct the graph promised by the legend from realistic SASE source state.

Dependencies: Phase 6.1.

Primary ownership:

- `../sase-core/crates/sase_core/src/artifact/ingest.rs`
- `../sase-core/crates/sase_core/tests/fixtures/`
- Rust ingestion tests under `../sase-core/crates/sase_core/src/artifact/` or `../sase-core/crates/sase_core/tests/`

Implementation shape:

- Inventory existing ingestion tests and consolidate fixture helpers where useful.
- Add or strengthen fixture scenarios for:
  - project files in both current and archive `*.gp` files
  - ChangeSpec parent links to project files
  - commit artifacts and commit payload metadata
  - directory artifact containment using longest-known parent
  - bead parent/child/dependency/work-ready states
  - phase bead to worker agent links
  - agent artifacts with named agents and legacy fallback IDs
  - agent-created files including transcripts, live replies, responses, diffs, plans, questions, raw prompts, logs,
    images/PDFs where supported, and markdown PDFs
  - retry, planner/coder, follow-up, feedback/question, and related ChangeSpec chains
  - thought extraction from supported provider logs/session files
  - stale cleanup modes `none`, `mark`, and destructive cleanup if implemented
- Add a mixed end-to-end fixture that rebuilds one temp graph containing projects, beads, agents, files, thoughts, and
  archive state, then validates doctor output and key navigation paths.
- Add targeted upsert coverage for project-file, bead-store, directory/file, and agent-artifact changes without
  requiring a full rebuild.

Acceptance checks:

- The mixed fixture graph is connected back to `/` except for intentionally diagnostic test nodes.
- `artifact_show` on representative Project, ChangeSpec, Commit, Bead, Agent, File, Directory, and Thought nodes returns
  expected payloads, children, and inbound/outbound links.
- Rebuilding the same fixture twice is deterministic and idempotent.
- Targeted upsert tests prove changed sources update affected rows without broad unrelated churn.

Suggested verification:

- In `../sase-core`: `cargo test -p sase_core artifact::ingest`.
- Run full `cargo test -p sase_core` if shared parser, bead, or agent-scan behavior is touched.

## Phase 6.3: PyO3 Binding And Python Facade Parity

Goal: prove every Rust artifact command exposed to Python has a stable, JSON-compatible contract and a strict Python
facade mirror.

Dependencies: Phases 6.1 and 6.2.

Primary ownership:

- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/artifact_wire/`
- `src/sase/core/artifact_facade.py`
- `tests/test_core_facade/test_artifact.py`
- any Rust/Python parity fixtures needed under `../sase-core/crates/sase_core/tests/fixtures/`

Implementation shape:

- Add parity tests for all exposed binding functions:
  - `artifact_add`
  - `artifact_remove`
  - `artifact_list`
  - `artifact_show`
  - `artifact_graph`
  - `artifact_export`
  - `artifact_rebuild`
  - `artifact_upsert_path`
  - `artifact_doctor`
- Verify Python dataclass/dict conversion keeps rectangular JSON shapes:
  - nulls are preserved where the wire contract expects nulls
  - lists default to empty lists
  - metadata/payload maps survive round-trip
  - schema version mismatches fail clearly
- Add negative tests for malformed add/remove requests, unsupported export format, invalid source kinds, invalid cleanup
  modes, and missing required fields.
- Add real-extension smoke tests that use temp SQLite indexes and synthetic source roots without touching user state.
- Ensure facade errors remain actionable when the Rust extension is missing or a binding is absent.

Acceptance checks:

- Python and Rust agree on all artifact wire field names and default values.
- Every binding has both a positive round-trip test and at least one invalid request/error-path test.
- Real-extension smoke tests exercise at least one manual graph, one rebuilt derived graph, one targeted upsert, one
  export, and one doctor call.

Suggested verification:

- In `../sase-core`: `cargo test -p sase_core_py artifact`.
- In this repo: `pytest tests/test_core_facade/test_artifact.py`.
- Finish with `just check` if Python files changed.

## Phase 6.4: CLI And Skill Contract Coverage

Goal: make `sase artifact` safe as an operator-facing quality gate and ensure the generated skill/docs reflect the
actual CLI contract.

Dependencies: Phase 6.3.

Primary ownership:

- `src/sase/main/parser_artifact.py`
- `src/sase/main/artifact_handler.py`
- `src/sase/xprompts/skills/sase_artifact.md`
- `docs/artifacts.md`
- `docs/xprompt.md`
- `tests/main/test_artifact_cli.py`
- `tests/main/test_init_skills_handler.py`

Implementation shape:

- Ensure parser tests cover every subcommand and every option, including the repo convention that every optional
  argument has a short form.
- Strengthen handler tests for:
  - JSON and human output for `add`, `remove`, `list`, `show`, `graph`, `rebuild`, and `doctor`
  - table truncation or compact formatting where applicable
  - multi-link add/remove parsing
  - unsupported formats and malformed link tuples
  - nonzero exit codes for doctor failures when implemented
  - default index path behavior without touching the real home directory
- Add CLI smoke tests using a temp SQLite index and the real facade where test cost is acceptable.
- Verify `docs/artifacts.md` covers every registered subcommand and includes current short-option examples.
- If `src/sase/xprompts/skills/sase_artifact.md` changes, regenerate installed skills with `sase init-skills --force`
  and update only generated outputs that are part of the established workflow.

Acceptance checks:

- `sase artifact --help` and each subcommand help path remain parser-valid.
- JSON output is stable enough for agents to consume in `/sase_artifact`.
- Human output includes the minimum diagnostic context needed for operators: IDs, kinds, link types, provenance/source,
  and doctor issue details.
- Skill/docs examples execute against the parser.

Suggested verification:

- `pytest tests/main/test_artifact_cli.py tests/main/test_init_skills_handler.py`.
- `just check`.

## Phase 6.5: TUI Modal And Keybinding Quality Gate

Goal: prove the `A` artifact panel is behaviorally stable, fast on large fake graphs, and independent of broad graph
scans during cursor movement.

Dependencies: Phase 6.3.

Primary ownership:

- `src/sase/ace/tui/actions/artifacts.py`
- `src/sase/ace/tui/artifact_graph_refresh.py`
- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_state.py`
- `src/sase/ace/tui/modals/artifact_panel_renderers.py`
- `src/sase/ace/tui/modals/help_modal/bindings.py`
- `src/sase/default_config.yml`
- `tests/ace/tui/test_artifact_panel_launch.py`
- `tests/ace/tui/test_artifact_graph_refresh.py`
- `tests/ace/tui/modals/test_artifact_panel_modal.py`
- `tests/ace/tui/modals/test_artifact_panel_renderers.py`
- keybinding/footer tests under `tests/test_keybinding_footer*.py`

Implementation shape:

- Strengthen launch-context tests for:
  - AXE tab opens `/`
  - CLs tab opens the current ChangeSpec ID and passes project-file context
  - Agents tab prefers stable agent name and falls back to legacy ID
  - missing context produces a warning instead of crashing
- Strengthen modal behavior tests:
  - loading/error/missing states
  - retry-once targeted refresh for missing start artifacts
  - back/forward/parent/root navigation
  - text filter updates without Rust requery
  - row movement does not call `artifact_show`, `artifact_graph`, `artifact_export`, or rebuild helpers
  - opening selected row calls exactly one narrow `artifact_show`
  - graph preview/export actions are explicit and bounded
- Strengthen renderer tests for all supported artifact kinds:
  - root, file, directory, project, ChangeSpec, commit, bead, agent, thought, and unknown kinds
  - missing files and missing payloads
  - large text/diff previews and image-path fallback behavior
- Strengthen keybinding/footer/help tests for `A` as "Artifacts" and legacy run log demotion.

Acceptance checks:

- TUI tests use mocked artifact facade responses and never depend on the real Rust extension or user graph state unless
  a test explicitly opts into a temp real-extension smoke.
- A large fake graph benchmark records open latency and query counts for AXE, CLs, and Agents contexts.
- Tests fail if normal `j/k` movement triggers broad graph work.

Suggested verification:

- `pytest tests/ace/tui/test_artifact_panel_launch.py tests/ace/tui/test_artifact_graph_refresh.py tests/ace/tui/modals/test_artifact_panel_modal.py tests/ace/tui/modals/test_artifact_panel_renderers.py tests/test_keybinding_footer_core.py tests/test_keybinding_footer_status.py`.
- `just check`.

## Phase 6.6: Integrated Performance And Final Gate

Goal: run the end-to-end quality gate, add durable performance measurements, and fix any remaining cross-boundary
failures exposed only by integration.

Dependencies: Phases 6.1 through 6.5.

Primary ownership:

- `tests/perf/` or focused benchmark tests under the existing perf structure
- any final fixes in Rust, Python facade/CLI, or TUI files implicated by integration failures
- documentation for running the quality gate if existing docs lack it

Implementation shape:

- Add deterministic performance measurements for:
  - full graph rebuild from a mixed temp fixture
  - targeted project-file upsert
  - targeted bead-store upsert
  - targeted agent-artifact upsert
  - `artifact_show` on common high-value node kinds
  - modal open latency on a large fake graph
- Keep thresholds conservative. Prefer printing/documenting latency and query counts plus asserting only clear
  regressions such as accidental broad scans or unbounded output.
- Run the full Rust suite in `../sase-core`.
- Run `just install` and `just check` in this repo.
- Triage failures by fixing the smallest implementation or test-contract issue.
- Update `docs/artifacts.md` or the debug/perf runbook with the final quality gate commands if they are not already
  documented.

Acceptance checks:

- `cargo test` passes in `../sase-core`.
- `just install` then `just check` passes in this repo.
- Performance output includes fixture size, operation name, latency, mutation or query counts, and whether the
  graph/modal call was intentionally bounded.
- No test or benchmark reads or mutates the user's real artifact index.

Suggested verification:

- In `../sase-core`: `cargo test`.
- In this repo: `just install && just check`.

## Cross-Phase Guardrails

- Treat Epic 6 as test-first hardening. Add product code only to repair a contract violation discovered by the new
  tests.
- Keep fixtures local, deterministic, and independent of machine-specific timestamps except where timestamp behavior is
  the thing under test.
- Prefer focused module tests over slow full-stack tests until Phase 6.6.
- Do not duplicate large fixtures across phases; if a helper becomes shared, move it to a clear test support module
  within the relevant repo.
- Preserve the Rust core boundary: graph identity, traversal, ingestion, doctor, and export semantics stay in Rust;
  Python verifies adapters and presentation.
- Maintain uniform runtime behavior across Claude, Gemini, Codex, and plugin providers.
- If a phase touches both repos, document both verification commands in its final response.

## Suggested Agent Order

1. Phase 6.1 first. It locks down graph primitive behavior.
2. Phase 6.2 second. It validates source-derived graph construction using the primitive contracts.
3. Phase 6.3 third. It proves Rust/Python wire parity after the Rust graph contract is stable.
4. Phase 6.4 and Phase 6.5 can run after Phase 6.3. They mostly own disjoint CLI/docs and TUI surfaces.
5. Phase 6.6 last. It runs the integrated gate and closes cross-boundary gaps.
