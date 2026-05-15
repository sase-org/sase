---
create_time: 2026-05-15 10:50:47
status: done
prompt: sdd/prompts/202605/bead_event_log_migration.md
bead_id: sase-3n
tier: epic
---
# Plan: Canonical Bead Event Log Migration

## Goal

Replace `sdd/beads/issues.jsonl` as the canonical bead store with a Rust-owned append-only event log, while preserving
legacy `issues.jsonl` support as an import/export and compatibility projection. Existing bead data in this repository
must be migrated into the new file structure before the migration is considered complete.

The design follows the relevant recommendation from `sdd/research/202605/sase_tui_agents_tab_mvp_research.md`: shared
backend facts belong in `../sase-core`, and frontends/CLI code should consume a UI-neutral snapshot produced by pure
reducers rather than reimplementing storage semantics locally.

## Canonical Storage Shape

Use a sharded event-log structure under the existing bead directory:

```text
sdd/beads/
  config.json                    # project config and owner/prefix metadata; not bead state truth
  metadata.json                  # existing metadata, preserved
  events/
    manifest.json                # event-store schema version and migration metadata
    streams/
      <top-level-bead-id>.jsonl   # canonical append-only event stream for a plan/epic/legend and its phase children
  issues.jsonl                   # legacy generated projection, retained for compatibility
  beads.db                       # legacy/cache mirror, retained while compatibility callers still need it
```

Each event stream owns one aggregate rooted at a top-level bead ID. Phase bead events live in the parent stream.
Cross-epic dependencies are represented as events on the dependent issue's stream and resolved after all streams reduce.
This avoids one giant frequently-conflicting file while keeping the canonical source of truth auditable and append-only.

Event records should be versioned and self-describing:

```json
{
  "schema_version": 1,
  "event_id": "deterministic-or-generated-id",
  "timestamp": "2026-05-15T00:00:00Z",
  "actor": "user@example.com",
  "operation": "issue_created",
  "issue_id": "sase-1.1",
  "payload": {}
}
```

The first reducer target is the current `IssueWire` snapshot model. That keeps the public CLI, mobile helper, work
planner, and TUI bead display surfaces stable while the source of truth changes underneath them.

## Compatibility Rules

- Reads prefer `events/manifest.json` + `events/streams/*.jsonl`. If the event store is absent, fall back to
  `issues.jsonl`.
- Writes append canonical events first, then regenerate `issues.jsonl` and refresh/rebuild `beads.db` as compatibility
  mirrors.
- Legacy `issues.jsonl` import remains supported indefinitely enough for old workspaces and tests.
- The generated `issues.jsonl` should remain byte-stable where current tests depend on stable compact JSON output.
- `sase bead sync`, `doctor`, commit helpers, and messages must learn that canonical mutations include
  `sdd/beads/events/**`; any old text saying only `sdd/beads/issues.jsonl` changed should be updated.

## Phase 1: Event Schema, Reducer, and Fixtures

Owner: one agent instance.

Write scope:

- `../sase-core/crates/sase_core/src/bead/**`
- `../sase-core/crates/sase_core/tests/**`
- fixture copies under `../sase-core/crates/sase_core/tests/fixtures/bead/**`
- no production Python behavior changes

Work:

- Add Rust bead event wire types, event-store manifest type, and event validation.
- Implement import from existing `IssueWire` snapshots into deterministic event streams.
- Implement pure reduction from event streams into `Vec<IssueWire>`.
- Cover every current mutation outcome with event operation variants: `issue_created`, `issue_updated`, `issue_opened`,
  `issue_closed`, `issue_removed`, `dependency_added`, `ready_marked`, `ready_unmarked`, `epic_work_preclaimed`, and any
  existing cascade/remove semantics.
- Add fixtures that prove `issues.jsonl -> events -> issues` preserves the current schema, including tiers, ChangeSpec
  metadata, model, epic_count, dependencies, closed issues, and corrupt legacy JSONL handling.
- Define deterministic stream ordering and event ordering so generated files are stable in git.

Exit criteria:

- Rust tests demonstrate round-trip parity against the current JSONL fixtures.
- No Python call site observes the new event store yet.

## Phase 2: Canonical Read Engine and Python Facade

Owner: one agent instance.

Write scope:

- `../sase-core/crates/sase_core/src/bead/read.rs`
- `../sase-core/crates/sase_core/src/bead/mod.rs`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/bead_read_facade.py`
- focused read tests in `tests/test_core_facade/` and `tests/test_bead/`

Work:

- Change Rust `read_store_issues()` to prefer the event store and fall back to `issues.jsonl`.
- Expose event-store diagnostics through `doctor()`: missing events, missing legacy projection, projection drift,
  invalid events, orphan phase records after reduction.
- Add PyO3 bindings for explicit migration/read helpers as needed, using dict/list payloads consistent with the current
  `bead_*` bindings.
- Add tests that create both stores and prove canonical events win over stale `issues.jsonl`.
- Keep ordering/filtering behavior for `show`, `list`, `ready`, `blocked`, `stats`, and `get_epic_children`.

Exit criteria:

- Existing read commands pass with legacy-only stores.
- New tests prove event-backed reads are the source of truth when both stores exist.

## Phase 3: Event-Backed Mutations and Mirror Generation

Owner: one agent instance.

Write scope:

- `../sase-core/crates/sase_core/src/bead/mutation.rs`
- `../sase-core/crates/sase_core/src/bead/jsonl.rs`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/bead_mutation_facade.py`
- focused mutation tests in both repos

Work:

- Update all Rust mutation operations to append canonical events rather than rewriting canonical snapshots.
- Regenerate `issues.jsonl` from the reduced event store after successful mutations.
- Keep `beads.db` refresh behavior available for Python compatibility wrappers.
- Preserve ID allocation semantics: top-level base36 IDs, phase `<parent>.<N>` IDs, config prefix handling, and current
  `next_counter` behavior.
- Ensure multi-issue operations are atomic enough for local git workflows: write stream temp files, fsync where
  practical, then replace projection mirrors only after event append succeeds.
- Add projection-drift tests that mutate events, regenerate `issues.jsonl`, and compare against expected snapshots.

Exit criteria:

- All current create/update/open/close/remove/dep/ready/preclaim behavior is preserved.
- A failed mirror write cannot silently leave a successful canonical event append unreported.

## Phase 4: CLI, Sync, Workflows, and User-Facing Text

Owner: one agent instance.

Write scope:

- `src/sase/bead/**`
- `src/sase/main/bead_fast_path.py`
- `src/sase/main/parser_bead.py`
- `src/sase/default_config.yml`
- `src/sase/xprompts/skills/sase_beads.md`
- CLI golden fixtures and bead workflow tests

Work:

- Update `sase bead` fast path and normal path to use the event-backed facades.
- Update `sync`, `sync --status`, auto-commit, and `sase bead work` commit logic to stage/commit `sdd/beads/events/**`
  plus the compatibility projections.
- Replace stale user-facing messages that mention only `issues.jsonl`.
- Keep public command names, flags, output shape, and exit codes stable unless a fixture documents an intentional
  change.
- Verify automation prompts still tell agents to mutate beads only through `sase bead`, not by editing storage files.

Exit criteria:

- CLI golden tests pass with the new canonical files present.
- `sase bead work` commits all canonical and compatibility bead files needed by another checkout to read the same state.

## Phase 5: Repository Data Migration

Owner: one agent instance.

Write scope:

- `sdd/beads/events/**`
- `sdd/beads/issues.jsonl`
- `sdd/beads/beads.db`
- `sdd/beads/metadata.json` only if the migration metadata explicitly requires it

Work:

- Run the Rust migration on this repository's current `sdd/beads/issues.jsonl`.
- Generate `events/manifest.json` and one stream file per top-level bead aggregate.
- Regenerate `issues.jsonl` from events and verify it is semantically equivalent to the pre-migration file.
- Rebuild or refresh `beads.db` as a compatibility cache.
- Run `sase bead doctor` and add/fix diagnostics until it reports the event store as canonical and healthy.
- Do not hand-edit memory files.

Exit criteria:

- Existing beads are readable from the event store without relying on `issues.jsonl`.
- A deliberate edit to stale `issues.jsonl` does not affect `sase bead show/list` while events are present.

## Phase 6: Full Verification, Docs, and Cleanup

Owner: one agent instance.

Write scope:

- tests touched by failures
- `docs/beads.md`
- `docs/rust_backend.md`
- focused SDD docs if they describe bead storage

Work:

- Run `just install` before validation in this workspace.
- Run focused Rust tests in `../sase-core`.
- Run focused Python bead tests, mobile helper bead tests, and agent bead display tests.
- Run `just check` in this repo after source changes.
- Update docs to describe events as canonical, `issues.jsonl` as a compatibility projection, and the fallback behavior.
- Search for stale claims that `issues.jsonl` is the source of truth and update live docs/config/help text, but leave
  old historical SDD transcripts alone unless they are active generated prompts or tests.

Exit criteria:

- `just check` passes in `sase_100`.
- `cargo test --workspace` or the documented focused equivalent passes in `../sase-core`.
- Docs and help text no longer direct users or agents to edit `issues.jsonl` as canonical storage.

## Cross-Phase Handoff Notes

- Each phase should start by checking `git status --short` in both `sase_100` and `../sase-core`; do not revert
  unrelated user or agent changes.
- Phases that touch generated skill files must follow `memory/long/generated_skills.md` before editing generated
  outputs.
- The Rust/Python boundary should remain coarse-grained. Prefer one Rust call that performs a complete bead operation
  and returns a mutation summary over Python chains of read/modify/write calls.
- Keep the compatibility projection in place until a separate cleanup plan proves no supported caller still requires it.
