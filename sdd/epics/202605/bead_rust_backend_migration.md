---
create_time: 2026-05-01 16:17:09
bead_id: sase-1u
status: done
prompt: sdd/prompts/202605/bead_rust_backend_migration.md
---
# Plan: Make `sase bead` Fast With `sase-core`

## Goal

Move the performance-sensitive `sase bead` data model, storage, query, merge, and mutation logic from Python into the
required Rust backend (`sase_core_rs`, built from `../sase-core`) while preserving the public `sase bead` CLI behavior.

The user-facing target is not just "Rust exists somewhere." The target is that common commands such as:

- `sase bead list`
- `sase bead ready`
- `sase bead show <id>`
- `sase bead update <id> --status ...`
- `sase bead work <epic_id> --dry-run`

feel effectively instant on normal bead stores and remain predictable on large stores.

## Current State

`sase bead` is currently Python-owned:

- CLI parser and dispatch: `src/sase/main/parser_bead.py`, `src/sase/main/entry.py`
- CLI handlers: `src/sase/bead/cli_*.py`
- data model: `src/sase/bead/model.py`
- SQLite access: `src/sase/bead/db.py`
- JSONL import/export: `src/sase/bead/jsonl.py`
- project API and mutations: `src/sase/bead/project.py`
- workspace merge view: `src/sase/bead/workspace.py`
- epic work DAG/prompt planning: `src/sase/bead/work.py`, `src/sase/bead/cli_work.py`

The Rust backend is already a hard runtime dependency:

- `pyproject.toml` depends on `sase-core-rs>=0.1.0,<0.2.0`.
- `src/sase/core/rust.py` strictly loads `sase_core_rs`.
- `../sase-core` already has a pure crate plus PyO3 crate.
- `docs/rust_backend.md` says there is no Python fallback for ported operations.

Local baseline on this workspace, with `sdd/beads/issues.jsonl` at 399 lines / 288K:

- `sase bead list`: about 0.32s
- `sase bead ready`: about 0.34s
- `sase bead show sase-16`: about 0.36s
- plain Python startup: about 0.08s
- importing `sase.main.entry`: about 0.23s
- importing `sase_core_rs`: about 0.02s

This means moving the DB logic to Rust is necessary but insufficient. A backend-only migration can improve large-store
work, but it will not make tiny commands feel "blazingly fast" if every invocation still builds the full Python parser
and imports broad command machinery. The plan therefore includes a dedicated `sase bead` fast path that dispatches to
one Rust CLI binding before the full top-level parser is built.

## Non-Goals

- Do not change the public `sase bead` command names, flags, output text, or exit-code behavior except where a phase
  explicitly records an intentional, reviewed compatibility change.
- Do not move agent launching, xprompt resolution, workspace provider plugin calls, VCS provider calls, telemetry
  plumbing, or user confirmation prompts into Rust. Rust should own deterministic bead data operations and planning;
  Python should keep host orchestration.
- Do not remove Python bead modules until Rust-backed parity, benchmarks, and call-site migration are complete.
- Do not silently fall back to Python for operations declared Rust-owned. Follow the existing `sase.core.rust` hard
  dependency model.
- Do not do cross-repo release/version changes casually. Any new PyO3 binding requires `sase-core-rs` version and
  packaging consideration.

## Architecture

Add a bead subsystem to `../sase-core/crates/sase_core` and expose it through `sase_core_rs`.

Rust should own:

- bead wire records and JSON conversion
- config parsing/writing
- JSONL import/export and tolerant corrupt-line skipping
- SQLite schema creation, migration, CRUD, ready/blocked/stats, and dependency queries
- workspace JSONL merge for read-only commands
- safe ID allocation helpers across discovered bead stores
- atomic-ish mutation batches for common write commands
- deterministic epic work DAG planning
- a narrow CLI-output planner for fast read/write commands

Python should own:

- storage-location discovery that depends on existing SASE workspace/config/plugin behavior
- resolving plan paths against the primary workspace
- telemetry metric increments until a later telemetry-specific migration justifies moving them
- xprompt lookup and agent launch in `sase bead work`
- human confirmation prompts
- compatibility wrappers for existing tests and internal imports during the migration

The Python/Rust boundary should be coarse-grained. For example, prefer:

```text
rust: bead_cli_execute(argv, cwd, resolved_store_context) -> {exit_code, stdout, stderr, mutation_summary}
```

over many per-row FFI calls. The current `sase_core_rs` style of dict/list wire payloads is fine; avoid PyO3 classes for
the first pass.

## Performance Targets

Set targets using a reproducible benchmark harness in Phase A, then enforce them later. Initial aspirational targets:

- `sase bead list`, `ready`, and `show` on the current 399-line store: p50 under 120ms from shell command start.
- Same commands through direct Rust bindings after Python has started: p50 under 10ms.
- Large synthetic store, 10k issues / 20k dependencies:
  - direct Rust read queries under 50ms p50
  - merged workspace read under 100ms p50 for three stores
  - write + JSONL export under 150ms p50
- No output parity drift for existing CLI tests.

If the shell-command target is missed because Python process startup remains dominant, the responsible phase must record
whether a native wrapper or console-script split is required as a follow-up.

## Phase Split

Each phase below is intended for one distinct agent instance. Agents should read this whole plan, then only own their
listed write scope.

### Phase A: Contract, Baselines, and Golden Fixtures

Purpose: freeze the current behavior and create the measurement harness before porting.

Write scope:

- `sase_100/tests/test_bead/`
- `sase_100/tests/perf/`
- `sase_100/docs/rust_backend.md`
- optional handoff doc under `plans/202605/`

Work:

- Add golden CLI fixtures for `init`, `create`, `list`, `show`, `ready`, `blocked`, `stats`, `dep add`, `update`,
  `open`, `close`, `rm`, `sync --status`, and error paths.
- Add JSONL/config fixture files covering:
  - current schema
  - pre-`is_ready_to_work` schema
  - pre-ChangeSpec metadata schema
  - corrupt JSONL lines
  - missing/empty JSONL
  - plan/phase hierarchy
  - dependencies, including cross-epic blockers
  - ChangeSpec metadata
- Add a benchmark harness that measures:
  - shell command latency for `sase bead list/ready/show`
  - Python direct `BeadProject` calls
  - workspace merged reads
  - synthetic large stores
- Document current measurements and proposed pass/fail gates.

Exit criteria:

- Focused bead tests still pass.
- Benchmark command is documented and can run without a Rust source edit.
- The next phase can use fixtures without re-discovering current behavior.

### Phase B: Rust Bead Wire, Config, JSONL, and Schema

Purpose: add the pure-Rust bead model and portable storage codecs without changing Python behavior.

Write scope:

- `../sase-core/crates/sase_core/src/bead/**`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_core/tests/**`
- Rust docs in `../sase-core/README.md`

Work:

- Add Rust wire structs for `Issue`, `Dependency`, `Status`, `IssueType`, config, operation errors, and operation
  outcomes.
- Match Python JSONL exactly, including field names, default handling, and compact export separators.
- Port validation rules from `src/sase/bead/model.py`.
- Implement config load/save with the same `config.json` shape.
- Implement JSONL import/export with tolerant skipping of corrupt lines.
- Model SQLite schema and migrations in Rust, but keep DB operations mostly unexposed until Phase C.
- Add Rust unit tests using Phase A fixtures.

Exit criteria:

- `cargo fmt --all` and `cargo test --workspace` pass in `../sase-core`.
- Rust JSONL export of fixtures is byte-compatible where Python currently promises stable output.
- No production Python code has changed.

### Phase C: Rust Read Engine and Workspace Merge View

Purpose: make all read-only bead operations available through Rust bindings.

Write scope:

- `../sase-core/crates/sase_core/src/bead/**`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `sase_100/src/sase/core/bead_*`
- focused tests in `sase_100/tests/test_core_facade/` and `tests/test_bead/`

Work:

- Implement Rust read APIs:
  - open/rebuild bead store from JSONL when needed
  - `show`
  - `list`
  - `ready`
  - `blocked`
  - `stats`
  - `get_epic_children`
  - `doctor` read diagnostics where applicable
- Implement Rust merged workspace read from a list of bead directories, preserving current "latest `updated_at` wins"
  semantics.
- Expose PyO3 bindings with dict/list payloads.
- Add a Python facade under `src/sase/core/`, following existing `notification_store_facade.py` style.
- Keep `src/sase/bead` callers on Python in this phase, except tests may call the facade directly.

Exit criteria:

- Rust/Python parity tests pass for all read fixtures.
- Direct binding benchmarks show the data path is materially faster than Python on medium and large stores.
- Any known output or ordering incompatibility is documented before write migration starts.

### Phase D: Rust Mutations, ID Allocation, and Persistence

Purpose: move write operations into coarse-grained Rust transactions while preserving JSONL export and current schema.

Write scope:

- `../sase-core/crates/sase_core/src/bead/**`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `sase_100/src/sase/core/bead_*`
- focused mutation tests in both repos

Work:

- Implement Rust operations:
  - `init`
  - `create`
  - `update`
  - `open`
  - `close`
  - `rm`
  - `dep add`
  - `mark_ready_to_work`
  - `unmark_ready_to_work`
  - `sync_is_clean` and JSONL export
- Preserve ID generation:
  - top-level base36 counters
  - child IDs as `<parent>.<N>`
  - cross-workspace max-counter scan
  - config `next_counter` persistence only for top-level creates
- Preserve cascade behavior for plan close/remove.
- Add mutation outcome wires that let Python update telemetry without re-reading the store.
- Use single Rust calls for whole operations; avoid `show` then `update` FFI chains where one Rust transaction can own
  the consistency boundary.
- Keep non-VC SDD git initialization/commit orchestration in Python for now.

Exit criteria:

- Existing Python mutation tests have Rust parity equivalents.
- JSONL after each mutation matches Python behavior.
- Large-store write benchmarks are captured.

### Phase E: Python API Delegation With Compatibility Wrappers

Purpose: route `BeadProject` and `MergedBeadView` through Rust while keeping existing Python imports and tests stable.

Write scope:

- `sase_100/src/sase/bead/project.py`
- `sase_100/src/sase/bead/workspace.py`
- `sase_100/src/sase/bead/db.py` only if needed as a compatibility shim
- `sase_100/src/sase/bead/jsonl.py` only if needed as a compatibility shim
- `sase_100/tests/test_bead/`
- docs as needed

Work:

- Convert Rust issue/dependency dicts back into existing Python `Issue`/`Dependency` dataclasses at the boundary.
- Keep the public `BeadProject` methods and exception types compatible.
- Delegate read and write methods to Rust facades.
- Keep Python `db.py` functions available for tests or niche callers during this phase, but stop using them in the
  primary `BeadProject` path.
- Ensure `get_read_view()` uses Rust merged reads.
- Preserve auto-init behavior and location discovery.
- Preserve non-VC SDD commit behavior.

Exit criteria:

- `pytest tests/test_bead` passes.
- `sase bead list/ready/show/create/update/close` behavior matches Phase A golden output.
- No broad CLI fast path has landed yet; this phase is about internal delegation.

### Phase F: `sase bead` Fast Path and CLI Output Planning

Purpose: remove the full Python CLI/parser/import tax from common bead commands.

Write scope:

- `sase_100/src/sase/main/entry.py`
- possibly `sase_100/src/sase/main/bead_fast_path.py`
- `../sase-core/crates/sase_core/src/bead/**`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- CLI tests and perf tests

Work:

- Add an early branch in `main()` for `sys.argv[1] == "bead"` before `create_parser()` imports and builds every
  top-level parser.
- Implement a tiny Python argument normalizer for bead commands or delegate `argv` parsing to Rust. Keep argparse as the
  compatibility fallback for help text until parity is proven.
- Add a Rust binding that executes or plans common bead commands in one call:
  - read commands can return final stdout/stderr/exit code
  - write commands can return stdout/stderr/exit code plus telemetry mutation summary
  - commands requiring Python host logic return a structured "defer to Python handler" outcome
- Fast-path these commands first:
  - `list`
  - `show`
  - `ready`
  - `blocked`
  - `stats`
  - `open`
  - `update`
  - `close`
  - `dep add`
- Keep `work`, `init`, `create` with plan-path normalization, and `sync` eligible for deferral until their host-coupled
  behavior is explicitly handled.
- Preserve `sase bead --help` and subcommand help behavior. It is acceptable for help to use the slow argparse path.

Exit criteria:

- Shell latency for fast-pathed read commands drops substantially from the Phase A baseline.
- Golden CLI output/exit-code parity passes.
- Slow path remains available for host-coupled commands.

### Phase G: Rust Epic Work Planning

Purpose: move the deterministic part of `sase bead work` into Rust while leaving launch orchestration in Python.

Write scope:

- `../sase-core/crates/sase_core/src/bead/**`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `sase_100/src/sase/bead/work.py`
- `sase_100/src/sase/bead/cli_work.py`
- `tests/test_bead/test_work.py`, `tests/test_bead/test_cli_work.py`

Work:

- Port `build_epic_work_plan` to Rust:
  - validate epic exists and is `plan`
  - ignore closed phase children
  - detect cycles
  - reject unresolved out-of-epic blockers
  - preserve wave ordering by `(created_at, id)`
  - compute leaf waits for the land agent
- Expose a Rust binding returning `EpicWorkPlan` wire data.
- Keep `render_multi_prompt` in Python unless measurement proves it matters; rendering depends on Python
  xprompt/workflow objects and VCS context.
- Optionally add a Rust prompt-plan helper that only takes resolved xprompt names and context strings, but keep it
  deterministic and side-effect-free.
- Keep pre-claim, rollback, confirmation, collision detection, and `launch_agent_from_cwd()` in Python.

Exit criteria:

- Existing work-plan tests pass through Rust.
- `sase bead work <id> --dry-run` output is unchanged.
- Work-plan construction benchmark improves on large phase DAGs.

### Phase H: Cleanup, Docs, and Release/Version Gate

Purpose: finish the migration responsibly and prepare the backend change for release.

Write scope:

- `sase_100/src/sase/bead/**`
- `sase_100/src/sase/core/**`
- `sase_100/docs/beads.md`
- `sase_100/docs/rust_backend.md`
- `sase_100/README.md`
- `sase_100/pyproject.toml` if a `sase-core-rs` version bump is required
- `../sase-core` package metadata if a release bump is required

Work:

- Remove or clearly mark Python-only internals that are no longer primary paths.
- Update docs to describe Rust-owned bead operations and troubleshooting via `sase core health`.
- Add a `sase core health` representative bead binding probe if useful.
- Decide whether the new bindings require `sase-core-rs>=0.1.x` bump; update dependency constraints only when matching
  wheels/source install behavior are ready.
- Update CI to run:
  - Python bead tests
  - Rust bead tests
  - cross-repo parity tests
  - performance smoke/regression floor if stable enough for CI
- Run full verification:
  - `just install`
  - `just rust-check`
  - `just check`

Exit criteria:

- Docs and tests describe the new ownership clearly.
- No stale Python path is accidentally used by common `sase bead` commands.
- Release/version requirements are explicit.

## Recommended Dependency Graph

- Phase A blocks all implementation phases.
- Phase B blocks C and D.
- Phase C and D can proceed mostly sequentially; C should land first because it validates the wire/query shape.
- Phase E depends on C and D.
- Phase F depends on E for safe command behavior, but an agent can prototype the early dispatch shape after A if it does
  not wire production commands yet.
- Phase G depends on C and can run in parallel with D/E if it writes only the work-planning module, but integration into
  `cli_work.py` should wait until E is stable.
- Phase H runs last.

## Risks and Mitigations

- Python startup may dominate shell latency. Mitigation: Phase F early-dispatches before full parser construction and
  measures shell-level latency, not only direct Rust calls.
- SQLite behavior can drift across Python and Rust. Mitigation: preserve schema SQL, add fixture-driven migrations, and
  compare JSONL after every mutation.
- Workspace merge semantics are subtle. Mitigation: Phase C owns merged-view parity before Python delegation.
- ID allocation can collide across ephemeral workspaces. Mitigation: Phase D ports the existing cross-workspace max scan
  and tests concurrent stores explicitly.
- `sase bead work` has side effects beyond bead data. Mitigation: Rust owns only DAG planning; Python keeps launch,
  rollback, confirmation, and xprompt behavior.
- Releasing new PyO3 bindings without a matching wheel can break installs. Mitigation: Phase H treats `sase-core-rs`
  versioning and packaging as an explicit gate.

## Verification Checklist for Each Implementation Agent

Every phase that edits `sase_100` should run `just install` first if the workspace has not been refreshed, then at least
the focused tests for its scope. Before final handoff after code changes in this repo, run `just check`.

Every phase that edits `../sase-core` should run:

```bash
cd ../sase-core
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

Cross-repo phases should also rebuild the extension into this repo's venv:

```bash
just rust-install
sase core health -j
```

## Final Success Bar

The migration is complete when:

- common `sase bead` commands use Rust-owned data operations by default;
- fast-pathed commands avoid the full Python parser/import path;
- output and error behavior match the Phase A golden contract;
- large-store bead operations have benchmark evidence of substantial improvement;
- docs and health checks make stale/missing `sase_core_rs` failures obvious;
- the remaining Python bead code is intentionally host orchestration, not duplicate core storage/query logic.
