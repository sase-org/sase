---
create_time: 2026-04-29 17:30:00
status: done
bead_id: sase-1b.3
---
# Rust Backend Phase 6C Handoff — Backend Contract Audit And Fallback Tests

## Scope landed in this phase

Phase 6C audits every `dispatch(...)` call site under `src/sase/core/`,
pins the shipped vs. unported classification with cross-cutting tests at
the dispatcher layer, and tightens the `RustBackendUnavailableError`
message so users have a one-line answer for the failure mode Phase 6F
will introduce by default. The default backend is **unchanged** — Python
is still the default through Phase 6E and Phase 6F is the flip.

## Inventory and classification

The 17 dispatched operations under `src/sase/core/*_facade.py`
classify as:

**Shipped (12)** — register a Rust impl when `sase_core_rs` exposes the
matching attribute; missing binding under `SASE_CORE_BACKEND=rust`
raises `RustBackendUnavailableError` rather than silently falling back:

- `parse_project_bytes` (`parser_facade.py`)
- `parse_query`, `evaluate_query_many` (`query_facade.py`)
- `scan_agent_artifacts` (`agent_scan_facade.py`)
- `read_status_from_lines`, `apply_status_update`, `plan_status_transition`
  (`status_facade.py`)
- `parse_git_name_status_z`, `parse_git_branch_name`,
  `derive_git_workspace_name`, `parse_git_conflicted_files`,
  `parse_git_local_changes` (`git_query_facade.py`)

**Unported (5)** — explicit `rust_unavailable="python"` so Python keeps
running under Rust mode. Either the work is not yet ported (graph index,
query context / per-row evaluators) or duplicating it would re-execute
disk side effects (`transition_changespec_status`):

- `build_query_context`, `evaluate_query`, `evaluate_query_with_context`
  (`query_facade.py`)
- `build_changespec_graph_index` (`graph_index_facade.py`)
- `transition_changespec_status` (`status_facade.py`)

The pure decision step inside `transition_changespec_status` already
routes through Rust via `plan_status_transition` (Phase 4E), so the
side-effecting wrapper can stay Python-only without losing the Rust
planner integration. Dual-run is a no-op for operations without a
registered `rust_impl`, so the unported set never produces records in
`~/.sase/perf/core_dual_run.jsonl`.

## Changes in this repo

- `src/sase/core/backend.py`: rewrote the `RustBackendUnavailableError`
  message in `dispatch()` so it explicitly names (1) the operation,
  (2) the `sase_core_rs` extension module (via the existing
  `RUST_EXTENSION_MODULE_NAME` constant so the literal can never drift),
  and (3) the `SASE_CORE_BACKEND=python` escape hatch. The previous
  wording said "mark the operation as an explicit Python fallback,"
  which was developer-facing advice about the dispatch call site rather
  than a path the user could take. The new wording keeps the
  "Rust backend requested" prefix that existing tests match against.
- `tests/test_core_facade/test_backend_contract.py` (new): the
  cross-cutting Phase 6C contract audit. Pins:
  - `DEFAULT_BACKEND is Backend.PYTHON` (Phase 6F is still the flip).
  - Every shipped operation raises `RustBackendUnavailableError` under
    Rust mode when no `rust_impl` is registered, and the message
    contains the operation name, `sase_core_rs`, and
    `SASE_CORE_BACKEND=python`.
  - Every unported operation runs Python under Rust mode via
    `rust_unavailable="python"`.
  - `SASE_CORE_DUAL_RUN=1` is a no-op for operations without a
    `rust_impl` (no JSONL record is written).
  - `SASE_CORE_DUAL_RUN=1` combined with `rust_unavailable="python"` is
    also a no-op, pinning the side-effect contract for
    `transition_changespec_status`.
  - A facade-walking test that fails if a new `dispatch(operation=...)`
    call site is added without being classified into
    `SHIPPED_OPERATIONS` or `UNPORTED_OPERATIONS`. This is the
    structural guard Phase 6C exists to install: a future agent cannot
    silently add an ambiguous-fallback op to the facade.
- `docs/rust_backend.md`: added a "Backend Contract: Shipped vs.
  Unported Operations" subsection containing the full classification
  table (operation, facade module, class, Rust-mode behavior with no
  binding) and a roadmap entry for Phase 6C.

## Tests run in this workspace

```
.venv/bin/pytest tests/test_core_facade/test_backend_contract.py \
                 tests/test_core_backend.py \
                 tests/test_core_facade/ \
                 tests/test_core_git_query.py \
                 tests/test_core_agent_scan.py
```

163 passed locally. Existing per-facade missing-binding tests
(`tests/test_core_facade/test_parser.py`,
`tests/test_core_facade/test_query.py`,
`tests/test_core_facade/test_status.py`, `tests/test_core_git_query.py`,
`tests/test_core_agent_scan.py`) continue to pass against the new
error-message wording because each one matches by operation name only.
The single test that pinned the "Rust backend requested" prefix
(`tests/test_core_backend.py::test_dispatch_rust_without_impl_raises`)
also still passes — that prefix is preserved verbatim.

`just check` was run in this workspace after the edits and stays green.

## Out of scope (handed to later subphases)

- `Phase 6D` — backend health check command and user-facing diagnostics.
  The `RustBackendUnavailableError` text improvement here gives users a
  shell-readable error, but Phase 6D should still add a scriptable
  `sase core health --json` (or smallest equivalent) that does not rely
  on exercising a dispatched binding to surface module path / version /
  selected backend.
- `Phase 6E` — `is_workflow_complete` regression resolution. Untouched.
- `Phase 6F` — flipping `DEFAULT_BACKEND` to `Backend.RUST`. Phase 6C
  pins the contract that makes the flip safe; the flip itself is
  Phase 6F's job.
- `Phase 6G` — full CI matrix and dual-run parity gate. The new
  `tests/test_core_facade/test_backend_contract.py` enumerates the
  shipped/unported sets but does not add CI matrix scaffolding; that is
  Phase 6G's responsibility.

## Exit criteria

- [x] Every `dispatch(...)` call site under `src/sase/core/` is
      classified as shipped or unported, with the classification pinned
      by an automated test.
- [x] Each shipped operation raises `RustBackendUnavailableError` under
      `SASE_CORE_BACKEND=rust` when its Rust binding is absent or stale.
- [x] Each unported operation runs Python under Rust mode via
      `rust_unavailable="python"`.
- [x] Dual-run is a verified no-op for operations without a
      registered `rust_impl` (no JSONL records, no side-effect
      duplication).
- [x] The `RustBackendUnavailableError` message names the operation,
      the `sase_core_rs` extension, and the `SASE_CORE_BACKEND=python`
      escape hatch.
- [x] No facade silently masks a missing shipped binding — verified at
      the dispatcher level and at every per-facade entry point's
      existing missing-binding test.
- [x] `DEFAULT_BACKEND` is still `Backend.PYTHON`.
