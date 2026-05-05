---
create_time: 2026-05-05 08:32:38
status: wip
prompt: sdd/prompts/202605/unified_artifact_epic1.md
---
# Plan: Unified Artifact Epic 1

## Context

Epic 1 from `/home/bryan/projects/github/sase-org/sase_100/sdd/legends/202605/unified_artifacts.md` builds the Rust
graph substrate for SASE artifacts in the sibling Rust workspace at `../sase-core`.

The implementation should keep the same boundary used by the existing Rust backend work:

- `../sase-core/crates/sase_core` owns pure Rust wire records, SQLite persistence, query/export logic, and Rust tests.
- `../sase-core/crates/sase_core_py` owns PyO3 functions exposed as the `sase_core_rs` Python extension.
- This repo (`sase_101`) should only receive thin Python wire/facade stubs if a phase needs them to pin the
  cross-language contract. Full `sase artifact` CLI work belongs to Epic 3.

The existing `agent_scan/index.rs` is the closest local model for SQLite setup: create parent directories, open with a
busy timeout, enable WAL and foreign keys, store canonical JSON payloads, maintain a `meta` schema version, and provide
deterministic query results. The artifact graph should follow that style while staying general enough for Epic 2
ingestion and Epic 4 TUI use.

## Product Contract

Epic 1 should leave behind a usable manual graph index with stable Rust and Python-callable operations, even before
source ingestion exists.

Artifact IDs:

- `/` for the root directory sentinel.
- Absolute normalized paths for file and directory artifacts.
- Project file paths for project artifacts.
- ChangeSpec `NAME` values for ChangeSpec artifacts.
- `<changespec_name>:<commit_number>` for commit artifacts.
- Bead IDs for bead artifacts.
- Agent names or documented legacy fallback IDs for agent artifacts.
- `thought:<sha256-prefix>` for thought artifacts.

Initial link types:

- `parent`: child -> parent.
- `created`: creator -> created artifact.
- `worker`: bead -> responsible agent.
- `related`: non-hierarchical relationships.

The database path used by later Python code should default to `~/.sase/artifacts.sqlite`, but every Rust/PyO3 entry
point should accept an explicit index path so tests and future callers can use temp databases.

## Phase 1: Wire Contract And Schema

Owner: one agent working only in `../sase-core/crates/sase_core`, except for optional Python fixture generation notes in
tests.

Implement:

- Add `src/artifact/mod.rs` and `src/artifact/wire.rs`.
- Define `ARTIFACT_WIRE_SCHEMA_VERSION` and rectangular serde records: `ArtifactKindWire`, `ArtifactNodeWire`,
  `ArtifactLinkWire`, `ArtifactDetailWire`, `ArtifactQueryWire`, `ArtifactGraphWire`, mutation result records, doctor
  result records, and export request/result records if useful for later phases.
- Use lowercase snake_case JSON fields, explicit `schema_version` on top-level response records, and always-present
  lists/options matching existing SASE wire conventions.
- Define a SQLite schema initializer with versioning for: `artifacts`, `artifact_links`, `artifact_payloads`,
  `source_watermarks`, `manual_tombstones`, and `meta`.
- Add indexes for artifact ID, kind, source labels, link type, source/target IDs, reverse parent children, and text
  search fields needed by list/search.
- Export the new module and wire records from `sase_core::lib`.

Acceptance checks:

- `cargo test -p sase_core artifact::wire`
- `cargo test -p sase_core artifact::schema` or equivalent targeted tests.
- Tests pin JSON shapes and schema initialization/idempotency.

Handoff notes:

- Keep database behavior minimal in this phase: opening and schema creation are enough. Do not implement graph mutation
  semantics here beyond what schema tests need.
- Make tombstone rows generic enough to suppress either derived nodes or derived links without deleting source data in
  Epic 2.

## Phase 2: Persistence Mutations

Owner: one agent working in `../sase-core/crates/sase_core/src/artifact`.

Depends on Phase 1.

Implement:

- Open/create artifact indexes with WAL, foreign keys, and transactions.
- Add/upsert manual and derived nodes.
- Remove manual nodes and tombstone derived nodes.
- Add/upsert manual and derived links.
- Remove manual links and tombstone derived links.
- Keep node payload/detail JSON in `artifact_payloads`, separate from indexed summary columns used for list/search.
- Enforce root invariants: root `/` exists or is created by initialization; root has kind `directory`; root cannot have
  a `parent` edge; non-root `parent` edges point child -> parent.
- Make upserts deterministic and idempotent.

Acceptance checks:

- Rust unit tests for add/upsert/remove node, add/remove link, duplicate upserts, derived tombstones, manual vs derived
  behavior, root invariants, and transaction rollback on invalid mutations.
- `cargo test -p sase_core artifact::`

Handoff notes:

- Do not implement broad source scanners. Mutations should accept wire records from future ingestion phases.
- Prefer stable internal helper APIs that Phase 3 queries can reuse instead of embedding SQL in tests.

## Phase 3: Core Read Queries And Doctor

Owner: one agent working in `../sase-core/crates/sase_core/src/artifact`.

Depends on Phases 1 and 2.

Implement:

- `show` and `detail` for one artifact ID.
- `list` and `search` with filters for kind, text, source, link type, reachability, and limits.
- `neighbors` with typed inbound/outbound link groups.
- `tree_children` by reverse `parent` links.
- `path_to_root` by forward `parent` links.
- Root reachability checks.
- `artifact_doctor` diagnostics for dangling links, unreachable nodes, duplicate logical IDs if any schema path can
  create them, stale payload rows, and schema version mismatches.
- Deterministic ordering for every list: stable kind/order keys first, then ID.

Acceptance checks:

- Rust unit tests for directionality, inbound/outbound grouping, children ordering, path-to-root ordering, root
  reachability, search ordering, dangling link diagnostics, and pagination/limit behavior.
- `cargo test -p sase_core artifact::`

Handoff notes:

- Keep query response shapes narrow and directly useful for the future TUI: selected node detail, children page, links
  page, and optional payload preview.
- If full-text search is deferred to `LIKE` in Epic 1, document the seam in the code/tests so Epic 2 or 3 can upgrade it
  without changing the wire shape.

## Phase 4: Graph Materialization And Export

Owner: one agent working in `../sase-core`.

Depends on Phases 1 through 3.

Implement:

- Add `petgraph` to the workspace/crate dependencies.
- Materialize bounded subgraphs around a root artifact by depth, direction, and optional link type filters.
- Materialize full graph snapshots with conservative default limits.
- Export graph results as: JSON wire (`ArtifactGraphWire`), DOT, Mermaid.
- Keep exports deterministic: stable node ordering, stable edge ordering, and escaped labels.
- Return clear truncation metadata when limits are hit.

Acceptance checks:

- Rust tests for bounded depth, link type filtering, full graph limits, deterministic DOT/Mermaid output, escaping, and
  truncation metadata.
- `cargo test -p sase_core artifact::`

Handoff notes:

- This phase should not alter mutation/query semantics except where graph materialization exposes missing helper
  functions.
- Use graph export records that map cleanly to future `sase artifact graph` output modes.

## Phase 5: PyO3 Bindings And Python Wire Stubs

Owner: one agent working in both `../sase-core/crates/sase_core_py` and this repo's `src/sase/core`/`tests`.

Depends on Phases 1 through 4.

Implement:

- Expose PyO3 bindings in `sase_core_rs`: `artifact_add`, `artifact_remove`, `artifact_list`, `artifact_show`,
  `artifact_graph`, `artifact_rebuild`, `artifact_upsert_path`, `artifact_doctor`.
- For Epic 1, `artifact_rebuild` and `artifact_upsert_path` may be no-op or manual-only placeholders if source ingestion
  is still Epic 2, but their wire responses must be stable and explicit about what happened.
- Add Python dataclass wire helpers in `src/sase/core/artifact_wire.py`.
- Add a thin facade in `src/sase/core/artifact_facade.py` that calls `require_rust_binding`, converts Python dataclasses
  to dicts, and rehydrates Rust dict responses.
- Add tests that can run against a fake `sase_core_rs` for conversion behavior, plus direct-Rust tests guarded the same
  way current core tests are guarded.

Acceptance checks:

- In `../sase-core`: `cargo test`.
- In this repo after `just install`: targeted Python tests for `artifact_wire.py` and `artifact_facade.py`.
- The installed extension exposes all requested binding names.

Handoff notes:

- Do not add the `sase artifact` CLI in this phase unless only a tiny private proof helper is required for tests. CLI
  parser/handler work belongs to Epic 3.
- Keep every Python-facing argument explicit; later CLI code can choose the default `~/.sase/artifacts.sqlite`.

## Phase 6: Integration Hardening And Documentation

Owner: one final integration agent working across `../sase-core` and this repo.

Depends on all previous phases.

Implement:

- Review the complete Epic 1 surface for naming consistency and missing exports.
- Add compact developer documentation near the Rust artifact module describing: graph directionality,
  source/manual/tombstone semantics, schema versioning, default index path expectations, and the limits of Epic 1 before
  ingestion.
- Add or update parity tests proving Python wire conversion matches Rust JSON output for representative node, link,
  query, graph, mutation, and doctor records.
- Run full verification and fix integration fallout.

Acceptance checks:

- In `../sase-core`: `cargo test`.
- In this repo: `just install` then `just check`.
- No broad source ingestion, TUI panel, or public CLI behavior is included.

Handoff notes:

- This phase should be mostly stabilization. If it uncovers major missing primitives, patch them in the smallest owning
  module rather than starting Epic 2 work.

## Cross-Phase Rules

- Separate agents must not revert unrelated local changes in either repo.
- Each phase should begin with `git status --short` in both repositories.
- Keep `sase_core` PyO3-free; all Python object conversion stays in `sase_core_py` or Python facade code.
- Prefer structured serde/rusqlite APIs over ad hoc string handling.
- Keep all public wire records backward-compatible within the epic unless a phase deliberately bumps
  `ARTIFACT_WIRE_SCHEMA_VERSION` and updates tests.
- Every phase should leave targeted tests passing before handoff.
- The final phase owns full checks, but earlier agents should still run the most specific test commands for their scope.

## Out Of Scope For Epic 1

- Scanning project files, ChangeSpecs, commits, beads, agent artifact directories, or thoughts into graph rows.
- Public `sase artifact` CLI commands and generated `/sase_artifact` skill.
- Textual artifact panel, keybinding changes, or old panel removal.
- Migration from `~/.sase/agent_artifact_index.sqlite`.
- Runtime metadata writes from launch/retry/commit workflows.
