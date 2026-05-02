---
create_time: 2026-04-29 13:54:20
bead_id: sase-19.5
status: complete
---
# Rust Backend Phase 4E Handoff: Transition Decision Plan Integration

## Scope

Phase 4E threads the Phase 4C Rust planner through the status facade and
integrates it into `transition_changespec_status_python` so the pure
decision step routes to Rust under `SASE_CORE_BACKEND=rust` while every
side effect — atomic STATUS line rewrite, mentor flag mutation, suffix
renames, archive moves, timestamp recording, and VCS calls — stays on
Python. Dual-run compares Python and Rust plans before any side effects
fire, so plan drift surfaces in `~/.sase/perf/core_dual_run.jsonl`
without duplicating disk writes.

The user-visible entry point `transition_changespec_status` keeps its
`rust_unavailable="python"` fallback. Routing the entry point through
`SASE_CORE_DUAL_RUN=1` would otherwise execute every disk-bound side
effect twice; the planner wire is where the cross-language comparison
belongs.

## What landed

### Facade registration (`src/sase/core/status_facade.py`)

- New thin adapter `_rust_plan_status_transition_impl` looks up
  `sase_core_rs.plan_status_transition` via `load_rust_extension()`,
  marshals the request via `status_wire_to_json_dict`, and rehydrates
  the response through `status_plan_from_dict`. Mirrors the Phase 3C
  agent-scan / Phase 4D line-helper pattern: a clear `RuntimeError` if
  the extension disappears between the import probe and the call.
- New facade entry `plan_status_transition(request)` registers the Rust
  adapter as `rust_impl` whenever `sase_core_rs` is importable **and**
  exposes `plan_status_transition`. Phase 4E classifies the planner as a
  **shipped Rust operation** — missing bindings under
  `SASE_CORE_BACKEND=rust` raise `RustBackendUnavailableError` rather
  than silently falling back to Python.
- Module docstring updated to enumerate the three flavors (line helpers,
  planner, side-effecting transition) and explain why
  `transition_changespec_status` keeps `rust_unavailable="python"`.
- The transition entry point is unchanged in shape: `python_impl =
  transition_changespec_status_python` and `rust_unavailable="python"`.
  The Rust integration happens inside the Python implementation, not at
  this dispatch site.

### Refactored Python transition (`src/sase/status_state_machine/transitions.py`)

`transition_changespec_status_python` was rewritten to make the three
phase boundaries explicit. The new implementation is ~150 lines of
straight-line code with no branch-handler indirection:

1. **In-lock input gathering** — read project file, read STATUS line via
   the facade-routed `read_status_from_lines`, and call
   `build_status_transition_request(...)` (Phase 4B helper) to gather
   parent status, blocking children, sibling info, and existing-name
   set.
2. **Pure decision** — call `sase.core.status_facade.plan_status_transition(request)`,
   which dispatches to Rust under `SASE_CORE_BACKEND=rust` (and to the
   Python `plan_status_transition_python` otherwise). A failing plan
   short-circuits before any disk write.
3. **In-lock side effects** — apply the plan's `status_update_target`
   via `apply_status_update` + `write_changespec_atomic`, then mutate
   mentor flags per `mentor_draft_action`.
4. **Post-lock side effects** — execute `suffix_action` (via existing
   `handle_suffix_strip` / `handle_suffix_append`), `archive_action`
   (via `move_changespec_to_file`), and the timestamp recording (via
   `add_timestamp_entry_atomic`). Each one is driven by the typed plan
   fields, never re-derived from the raw status strings.

The branch-handler module `src/sase/status_state_machine/handlers.py`
was deleted: every responsibility it owned (validation, error message
formatting, suffix-action computation, mentor flag selection) moved to
the planner, and every side effect it performed (atomic write, mentor
mutation) moved to the in-lock side-effect stage. The companion helper
`check_siblings_for_unreverted_children` was deleted from
`siblings.py` for the same reason — `build_status_transition_request`
populates `request.siblings_with_unreverted_children` and the planner
formats the rejection string.

### Tests

- `tests/test_core_facade.py` gained six new tests for the planner
  facade (mirroring the Phase 4D line-helper structure):
  - `test_plan_status_transition_python_default_backend` — facade
    output equals `plan_status_transition_python` byte-for-byte under
    the default backend.
  - `test_plan_status_transition_rust_without_binding_raises` —
    `SASE_CORE_BACKEND=rust` with no `plan_status_transition` binding
    raises `RustBackendUnavailableError`.
  - `test_plan_status_transition_rust_backend_uses_rust_impl` — a fake
    `sase_core_rs.plan_status_transition` is invoked, the request was
    serialised via `status_wire_to_json_dict`, and the sentinel
    response reaches the caller.
  - `test_plan_status_transition_dual_run_logs_comparison` — under
    `SASE_CORE_DUAL_RUN=1` the facade calls both impls, returns the
    Python plan, and writes one matched JSONL record under operation
    name `plan_status_transition`.
  - `test_plan_status_transition_rust_error_surfaces` — Rust-side
    `ValueError` propagates instead of silently falling back.
  - `test_plan_status_transition_real_extension_parity` — uses
    `pytest.importorskip(RUST_EXTENSION_MODULE_NAME)` so the test
    passes/skips cleanly without `sase_core_rs`. When installed it
    asserts the real binding's output matches
    `plan_status_transition_python` byte-for-byte.
- Two new end-to-end tests in the same file pin the integration:
  - `test_transition_changespec_status_uses_planner_facade` patches
    `sase.core.status_facade.plan_status_transition` to return a fake
    plan, then asserts the side-effect pipeline honours it (the STATUS
    line is rewritten using the plan's `status_update_target` and the
    request that reached the planner has the expected fields).
  - `test_transition_changespec_status_planner_failure_skips_side_effects`
    patches the planner to return `success=False` and patches
    `write_changespec_atomic` to fail if called. The transition returns
    `(False, old_status, error, [])` and the project file is byte-for-
    byte unchanged — the Phase 4E exit criterion that "Rust rejects a
    transition before writes occur".
- `tests/test_status_state_machine_transitions.py::test_draft_to_ready_records_timestamp_with_base_name`
  no longer patches `sase.status_state_machine.transitions.handle_ready_transition`
  (the symbol no longer exists). The test now exercises the real
  in-lock decision step via the planner, with mocks only on the
  out-of-lock side effects (`handle_suffix_strip`,
  `add_timestamp_entry_atomic`) and `find_all_changespecs`.
- Two existing assertions in
  `tests/test_status_state_machine_field_updates.py` and
  `tests/test_status_state_machine_transitions.py` were updated to
  match the Phase 4B-normalized rejection strings ("parent is Draft"
  vs. the old "parent 'Parent Feature' is Draft", and
  "sibling ChangeSpec 'foo_bar__2' has unreverted children" vs.
  "sibling ChangeSpec 'foo_bar__2' (Draft) has unreverted children").
  The deletion is justified by the deliberate Phase 4 contract — the
  request wire only carries the parent's status (not its NAME) and the
  sibling NAME (not its status). Updating the tests is the
  expectation-update path the Phase 4 plan explicitly allows.

### Documentation (`docs/rust_backend.md`)

- Opening paragraph and the `SASE_CORE_BACKEND` policy paragraph add
  `plan_status_transition` to the list of shipped Rust operations.
- The policy paragraph spells out why `transition_changespec_status`
  keeps `rust_unavailable="python"` (dual-run on the entry point would
  duplicate disk-bound side effects; the planner is the boundary).
- A new Phase 4E roadmap entry summarises the refactor: three explicit
  stages, planner-only Rust crossing, side effects exactly once
  regardless of backend, dual-run on the plan before side effects fire.

### Cleanup (`status_wire.py`, `status_wire_conversion.py`)

- Removed redundant `# pyvision: tests/test_core_status_wire.py`
  pragmas on `status_wire_to_json_dict`, `status_plan_from_dict`,
  `plan_status_transition_python`, and `build_status_transition_request`.
  The pyvision linter detected these as unnecessary because the
  symbols are now imported from `status_facade.py` and `transitions.py`.

## What did not change

- `src/sase/core/status_wire.py` — the Phase 4B request/plan wire
  contract is unchanged. Rust and Python share the same
  `STATUS_WIRE_SCHEMA_VERSION = 1`.
- `src/sase/core/status_wire_conversion.py::plan_status_transition_python`
  is unchanged — Phase 4E uses the existing pure planner as the
  Python implementation registered with the facade.
- `../sase-core/crates/sase_core_py` — Phase 4E is a Python-side
  integration. The Rust planner shipped in Phase 4C; no Rust source
  edits in this phase.
- Default backend stays `python`. The planner routes to Rust only
  under explicit `SASE_CORE_BACKEND=rust` selection.
- The line helpers `read_status_from_lines` / `apply_status_update`
  remain registered Phase 4D-style (rust_impl, no fallback). Routing
  inside the refactored transition still hits the facade and so still
  benefits from Rust under rust mode.

## Files changed in `sase_100`

- `src/sase/core/status_facade.py` — new `plan_status_transition`
  entry, Rust adapter, updated docstring; transition entry unchanged.
- `src/sase/core/status_wire.py` — removed two redundant pyvision
  pragmas.
- `src/sase/core/status_wire_conversion.py` — removed two redundant
  pyvision pragmas; reworded the sibling rejection comment.
- `src/sase/status_state_machine/transitions.py` — full rewrite around
  the planner (input gathering, plan dispatch, side-effect execution).
- `src/sase/status_state_machine/handlers.py` — **deleted** (its
  branch-handler functions were subsumed by the planner and the
  side-effect stages).
- `src/sase/status_state_machine/siblings.py` — removed
  `check_siblings_for_unreverted_children` (planner formats the
  rejection from `request.siblings_with_unreverted_children`).
- `tests/test_core_facade.py` — eight new tests covering planner
  facade routing, dual-run, real-extension parity, and end-to-end
  transition integration.
- `tests/test_status_state_machine_transitions.py` — dropped the
  `handle_ready_transition` patch in
  `test_draft_to_ready_records_timestamp_with_base_name`; updated the
  sibling-error assertion to the normalized format.
- `tests/test_status_state_machine_field_updates.py` — updated the
  parent-error assertion to the normalized format.
- `docs/rust_backend.md` — opening paragraph, backend-selection
  paragraph, and Phase 4E roadmap entry.
- `plans/202604/rust_backend_phase4_status_machine_phase4e_handoff.md`
  (this file).

## Commands run

```bash
just install
.venv/bin/pytest tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py \
  tests/test_core_backend.py \
  tests/test_core_dual_run.py \
  tests/test_core_facade.py \
  tests/test_core_status_lines.py \
  tests/test_core_status_wire.py
SASE_CORE_BACKEND=rust .venv/bin/pytest \
  tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py \
  tests/test_core_facade.py \
  tests/test_core_status_lines.py
just check
```

The default-backend run (138 tests), the `SASE_CORE_BACKEND=rust` run
(73 tests), and `just check` all pass on this workspace. The real-
extension parity test exercises the shipped
`sase_core_rs.plan_status_transition` binding directly when the
extension is installed; otherwise it skips with the standard
`pytest.importorskip` message.

## Hand-off to Phase 4F

The Phase 4F agent should:

1. Re-run the Phase 4A benchmark (`just bench-status-state-machine` or
   the equivalent script) against the refactored implementation under
   both `SASE_CORE_BACKEND=python` and `SASE_CORE_BACKEND=rust`,
   recording before/after numbers in
   `plans/202604/rust_backend_phase4_status_machine_phase4f_handoff.md`.
   The new code path adds one `status_wire_to_json_dict` →
   `plan_status_transition` → `status_plan_from_dict` round-trip per
   transition; the per-call cost should be small (the request wire is
   only ~5–10 fields) but the benchmark should confirm.
2. Review `~/.sase/perf/core_dual_run.jsonl` from local real-project
   runs with `SASE_CORE_DUAL_RUN=1` set. The mismatch count for
   `plan_status_transition` records must be zero before declaring the
   Rust planner stable. Mismatches typically surface as
   `first_diff_path` populated; investigate the exact field divergence.
3. Decide whether any status operation should default to Rust (the
   expected answer is still "no global default flip"; only recommend a
   per-operation default if shipped, packaged, parity-clean, and
   user-visible).
4. Update `sdd/research/202604/rust_backend_migration.md` Phase 4 status
   and `docs/rust_backend.md` roadmap with the final benchmark numbers
   and rollout decision.
5. Close out Phase 4 with the final handoff doc.

## Notes for follow-ups

- The planner is the only step that crosses the Rust boundary inside
  `transition_changespec_status_python`. The line helpers
  (`apply_status_update`) used in the in-lock side-effect stage still
  cross the boundary too, but they are Phase 4D operations — Phase 4E
  did not change their routing.
- The dual-run record's `input_hash` for `plan_status_transition` is
  computed from `repr(args)`, where `args = (request,)` and the
  request is a frozen dataclass. The `repr` is deterministic but
  potentially long for projects with many existing names; if the
  dual-run log grows unwieldy, consider a custom hashing strategy
  (e.g. hashing `status_wire_to_json_dict(request)` as a sorted JSON
  blob).
- The error string normalisation introduced in Phase 4B is now
  user-visible through the live transition path. If product-level
  feedback wants the parent NAME or sibling status restored, the right
  fix is to add `parent_name` / sibling-status fields to the request
  wire (a Phase 4F-or-later schema bump), not to bypass the planner
  in `transitions.py`.
- `transition_changespec_status` keeps `rust_unavailable="python"`
  intentionally. A future agent that wants to remove this asymmetry
  should first solve dual-run-without-side-effects (e.g. by splitting
  the entry point into a "plan-only" and an "apply-only" half), not
  by registering `transition_changespec_status_python` as both
  `python_impl` and `rust_impl` (which would duplicate every disk
  write under dual-run).
