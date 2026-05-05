---
create_time: 2026-05-05 08:58:22
status: wip
prompt: sdd/prompts/202605/unified_artifacts_epic1.md
bead_id: sase-23.1
tier: epic
legend_bead_id: sase-23
---
# Unified Artifacts Epic 1 Implementation Plan

## Scope

Implement Epic 1, "Rust Artifact Core And Persistence", from `sdd/legends/202605/unified_artifacts.md`.

This epic builds only the graph substrate in `../sase-core` plus the minimal Python-facing wire/binding parity surface
needed to validate it. It does not implement source ingestion, the `sase artifact` CLI, generated skills, or the TUI
artifacts panel. Those depend on this epic's stable graph contract.

The core rule is that shared backend behavior lives in `../sase-core/crates/sase_core`. The Python repo should only
receive thin wire records/facade tests if a phase needs them to prove binding compatibility.

## Current Architecture Context

`../sase-core` is a Rust workspace with:

- `crates/sase_core`: pure Rust domain logic, serde wire structs, SQLite code, and tests. This crate must remain free of
  PyO3 types.
- `crates/sase_core_py`: PyO3 bindings exported as `sase_core_rs`, returning Python dict/list shapes through serde JSON
  conversion.

The existing `agent_scan/index.rs` is the closest persistence precedent:

- `rusqlite` with bundled SQLite.
- `PRAGMA journal_mode = WAL`, `PRAGMA foreign_keys = ON`, and a `meta` table containing `schema_version`.
- Denormalized query columns plus canonical JSON payload columns.
- Deterministic query ordering and unit tests using temporary indexes.

Epic 1 should follow those conventions while creating a general artifact graph instead of another agent-specific index.

## Non-Goals For This Epic

- No project/ChangeSpec/commit/bead/agent/thought scanners.
- No automatic rebuild from existing SASE state beyond placeholder rebuild wiring that returns a clear "no source
  ingesters registered" result if needed by bindings.
- No `sase artifact` argparse command.
- No Textual modal, keybinding changes, or editor-opening behavior.
- No migration from `~/.sase/agent_artifact_index.sqlite`.

## Data Model Contract

Add a new `artifact` module under `crates/sase_core/src/artifact/`.

Artifact IDs are strings, with these reserved contracts from the legend:

- Root directory sentinel: `/`
- File artifacts: absolute normalized file path
- Directory artifacts: absolute normalized directory path, with `/` as root
- Project artifacts: absolute `~/.sase/projects/*/*.gp` file path
- ChangeSpec artifacts: ChangeSpec `NAME`
- Commit artifacts: `<changespec_name>:<commit_number>`
- Bead artifacts: bead ID
- Agent artifacts: stable agent name or documented fallback ID
- Thought artifacts: `thought:<sha256-prefix>`

Link direction must match the legend:

- `parent`: child -> parent. Reverse traversal gives tree children.
- `created`: creator -> created artifact.
- `worker`: bead -> responsible agent.
- `related`: non-hierarchical association.

Initial schema tables:

- `artifacts`
- `artifact_links`
- `artifact_payloads`
- `source_watermarks`
- `manual_tombstones`
- `meta`

Rows should distinguish manual and derived provenance. Removing a manual row deletes the manual row. Removing a derived
row creates a tombstone overlay and does not delete source files or source metadata. Phase 1 should implement the
overlay mechanics even though source ingesters arrive in Epic 2.

## Phase Breakdown

Each phase below is intended for one distinct implementation agent. Phases are ordered because later phases depend on
earlier Rust APIs and schema choices.

### Phase 1: Wire Types, Module Skeleton, And Schema

Owner scope:

- `../sase-core/crates/sase_core/src/artifact/mod.rs`
- `../sase-core/crates/sase_core/src/artifact/wire.rs`
- `../sase-core/crates/sase_core/src/artifact/store.rs`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_core/Cargo.toml` only if additional existing workspace dependencies are required

Implementation:

- Define `ARTIFACT_WIRE_SCHEMA_VERSION`.
- Add serde wire records:
  - `ArtifactKindWire`
  - `ArtifactNodeWire`
  - `ArtifactLinkWire`
  - `ArtifactDetailWire`
  - `ArtifactQueryWire`
  - `ArtifactGraphWire`
  - mutation/result records for node/link add/remove/upsert operations
  - doctor/export option records if their shape is needed by later phases
- Use rectangular JSON shapes:
  - explicit `schema_version` on top-level response/request records
  - snake_case keys
  - `Option<T>` serialized as `null`
  - lists serialized as `[]`
  - deterministic field order matching declared struct order
- Define controlled string constants or enums for initial artifact kinds and link types while still allowing future
  extension without a migration crisis.
- Implement `open_artifact_store(index_path)` or equivalent internal helper.
- Create the SQLite schema with version initialization and indexes for:
  - artifact `id`
  - artifact `kind`
  - artifact source/provenance fields
  - link `link_type`
  - link `source_id`
  - link `target_id`
  - reverse `parent` children lookup
  - text search fields
- Insert or ensure the root `/` artifact when the store is initialized.

Tests:

- Wire JSON shape snapshots for representative node/link/detail/query records.
- Schema initialization test verifies all tables, indexes, `meta.schema_version`, WAL mode, and root artifact presence.
- Reopening an existing DB is idempotent.

Exit criteria:

- `cargo test -p sase_core artifact::wire artifact::store`
- No Python repo changes unless a lightweight wire mirror is explicitly needed for parity tests in a later phase.

### Phase 2: Core Mutations And Overlay Semantics

Owner scope:

- `../sase-core/crates/sase_core/src/artifact/store.rs`
- Optional helper files under `../sase-core/crates/sase_core/src/artifact/`

Implementation:

- Implement transaction-backed operations for:
  - add/upsert node
  - remove node
  - add/upsert link
  - remove link
  - payload/detail upsert
- Enforce core invariants:
  - root `/` cannot be removed or tombstoned
  - duplicate upserts are idempotent
  - node and link identity is deterministic
  - link endpoints must exist unless the operation explicitly allows staging, and the default public API should reject
    dangling links
  - a `parent` link must be represented as child -> parent
- Implement manual-vs-derived behavior:
  - manual node/link removal deletes the manual row/link
  - derived node/link removal writes `manual_tombstones`
  - upserting a derived source respects tombstones
  - a manual re-add can either clear a tombstone or create an overriding manual row; document and test the chosen
    behavior
- Return mutation result records with counts and the affected IDs, not ad hoc booleans.

Tests:

- Add/upsert duplicate node and link.
- Remove manual node/link.
- Tombstone derived node/link without deleting source payload.
- Root removal is rejected.
- Parent directionality is child -> parent.
- Transactions roll back cleanly on invalid endpoints.

Exit criteria:

- `cargo test -p sase_core artifact`
- Mutation APIs are exported from `sase_core::artifact` and re-exported from `sase_core::lib.rs`.

### Phase 3: Query, Detail, Tree, And Doctor APIs

Owner scope:

- `../sase-core/crates/sase_core/src/artifact/query.rs`
- `../sase-core/crates/sase_core/src/artifact/store.rs`
- `../sase-core/crates/sase_core/src/artifact/mod.rs`

Implementation:

- Implement read APIs for:
  - `artifact_show`
  - `artifact_list`
  - text/kind/source filtering through `ArtifactQueryWire`
  - inbound/outbound neighbors grouped by link type
  - reverse-`parent` tree children
  - path-to-root by following forward `parent` links
  - root reachability checks
  - `artifact_doctor`
- Keep query responses deterministic:
  - stable sort by kind, display title, ID, or explicitly documented order
  - stable pagination/limit behavior
  - no broad graph scans for single-node detail unless requested
- Doctor should report, at minimum:
  - dangling links
  - missing root
  - unreachable non-root nodes
  - duplicate logical parent links where the schema permits detection
  - stale derived rows that are tombstoned or no longer have a source marker once source watermarks exist

Tests:

- Children query walks reverse `parent` links.
- Path-to-root walks forward `parent` links and handles cycles defensively.
- Neighbor queries preserve link direction and type.
- List/search ordering is deterministic.
- Doctor reports dangling/unreachable/cycle cases from fixture databases.

Exit criteria:

- `cargo test -p sase_core artifact`
- Public Rust functions cover all non-export Epic 1 query requirements.

### Phase 4: Graph Materialization And Export

Owner scope:

- `../sase-core/crates/sase_core/src/artifact/export.rs`
- `../sase-core/crates/sase_core/src/artifact/wire.rs`
- `../sase-core/crates/sase_core/Cargo.toml`
- Workspace `Cargo.lock`

Implementation:

- Add `petgraph` to the workspace dependencies and `sase_core`.
- Implement bounded subgraph materialization:
  - around a node
  - by depth
  - by link type filter
  - full graph snapshot with default and caller-supplied limits
- Implement deterministic exports:
  - JSON through `ArtifactGraphWire`
  - DOT
  - Mermaid
- Bound traversal by default to protect the TUI/CLI from accidentally exporting a large historical graph.
- Make limit truncation visible in the wire result, for example with `truncated: bool` and count fields.

Tests:

- DOT and Mermaid output are stable for a fixture graph.
- Depth and link-type filters include/exclude expected edges.
- Default limits truncate deterministically.
- Full graph export is stable across insertion order.

Exit criteria:

- `cargo test -p sase_core artifact`
- `cargo test -p sase_core` still passes with the new dependency.

### Phase 5: PyO3 Bindings In `sase_core_rs`

Owner scope:

- `../sase-core/crates/sase_core_py/src/lib.rs`
- `../sase-core/crates/sase_core_py/Cargo.toml` only if needed
- Binding tests in `../sase-core/crates/sase_core_py` or existing core tests

Implementation:

- Expose bindings named by the legend:
  - `artifact_add`
  - `artifact_remove`
  - `artifact_list`
  - `artifact_show`
  - `artifact_graph`
  - `artifact_rebuild`
  - `artifact_upsert_path`
  - `artifact_doctor`
- Bindings should accept primitive paths plus Python dict/list request records, convert through `serde_json::Value`,
  call pure Rust, and return Python dict/list structures using the existing conversion helpers.
- Release the GIL around SQLite work where current binding patterns support it.
- Keep error behavior consistent with current bindings: invalid wire payloads become `ValueError`; store/IO failures
  become a clear Python exception with the Rust error text.
- For `artifact_rebuild` and `artifact_upsert_path`, provide a minimal no-op or path-only implementation only if full
  source ingestion is not yet available. The response must make that limitation explicit so Epic 2 agents can replace it
  without ambiguity.

Tests:

- Binding smoke tests for every exported function.
- Invalid request shape raises the expected Python exception.
- Returned Python objects match `serde_json::to_value` from the Rust result.
- SQLite-backed mutations made through Python can be queried through Rust APIs.

Exit criteria:

- `cargo test -p sase_core_py`
- `cargo test` from `../sase-core`

### Phase 6: Python Wire Mirror And Parity Tests

Owner scope:

- `src/sase/core/artifact_wire.py`
- `src/sase/core/artifact_facade.py`
- `tests/test_core_artifact.py` or `tests/test_core_facade/test_artifact.py`
- No CLI parser/handler files

Implementation:

- Add Python dataclasses mirroring the Epic 1 wire records only if they are needed to prove binding compatibility before
  Epic 3.
- Add a strict facade that calls `require_rust_binding(...)` directly, following the current `agent_scan_facade.py`
  pattern.
- Add helper conversion functions:
  - dataclass -> JSON dict
  - JSON dict -> dataclass
  - query/options -> dict
- Keep this facade intentionally thin. Formatting, CLI defaults, and human table output belong to Epic 3.

Tests:

- Python wire shape tests match Rust JSON field names and null/list behavior.
- Facade calls the expected `sase_core_rs` functions with expected dicts.
- Missing/stale binding errors surface as `ImportError`/`AttributeError`, like the other strict Rust facades.
- If a local `sase_core_rs` build is installed, an integration test can create a temporary DB, add nodes/links, query
  them, and run doctor.

Exit criteria:

- In this repo, after any Python changes: `just install` then `just check`.
- In `../sase-core`: `cargo test`.

## Cross-Phase Handoff Rules

- Every phase should leave compiling Rust and focused tests passing.
- Every phase should update module exports so the next phase does not need to reach into private modules.
- Do not introduce runtime-specific behavior; Claude, Gemini, Codex, and plugin providers will all consume the same
  graph contract in later epics.
- Keep `sase_core` PyO3-free. All Python/native extension concerns stay in `sase_core_py`.
- Avoid changing this repo except for Phase 6's thin Python wire/facade tests or any unavoidable binding parity
  scaffolding.
- If a phase touches this repo, run `just install` before `just check` because SASE agent workspaces can have stale
  editable installs.
- If a phase touches `../sase-core`, run at least `cargo test -p <touched crate>` and prefer full `cargo test` before
  handoff.

## Suggested Approval Units

For bead or agent dispatch, create six phase beads matching the phases above. Only Phase 6 should touch the Python repo
by default. Phases 1-5 should be assigned ownership of `../sase-core` with narrow file scopes to avoid conflicts.

Recommended dependency chain:

1. Phase 1 blocks all others.
2. Phase 2 depends on Phase 1.
3. Phase 3 depends on Phase 2.
4. Phase 4 depends on Phase 3's graph query primitives.
5. Phase 5 depends on Phases 2-4 public Rust APIs.
6. Phase 6 depends on Phase 5 bindings.

## Final Epic Acceptance Criteria

- `../sase-core` has a pure Rust `artifact` module with versioned wire records, SQLite schema, mutation APIs, query
  APIs, doctor checks, and graph exports.
- `sase_core_rs` exposes the Epic 1 artifact functions with stable JSON-shaped Python objects.
- Tests cover directionality, root invariants, duplicate upserts, tombstones, query ordering, bounded exports, binding
  conversion, and Python wire parity.
- No source ingestion, CLI, or TUI behavior is accidentally bundled into Epic 1.
