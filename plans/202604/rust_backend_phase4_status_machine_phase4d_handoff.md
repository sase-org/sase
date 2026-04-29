---
create_time: 2026-04-29 13:38:19
bead_id: sase-19.4
status: complete
---
# Rust Backend Phase 4D Handoff: Facade Registration, Dual-Run, and Pure Helper Routing

## Scope

Phase 4D wires the Phase 4C PyO3 bindings into the existing
`sase.core.status_facade` dispatcher. After this phase
`SASE_CORE_BACKEND=rust` routes the **pure line helpers**
(`read_status_from_lines`, `apply_status_update`) through
`sase_core_rs`, while everything else on the status facade — most
notably the side-effecting `transition_changespec_status` — keeps
running in Python. The Rust planner (`plan_status_transition`) and
its host integration are explicitly Phase 4E targets and are **not**
registered on the Python facade in this phase.

## What landed

### Facade registration (`src/sase/core/status_facade.py`)

- New thin adapters `_rust_read_status_from_lines_impl` and
  `_rust_apply_status_update_impl` look up `sase_core_rs` via
  `load_rust_extension()` and forward the same positional arguments
  the Python helpers expect. They re-raise `RuntimeError` with a
  clear message if the extension disappears between
  `is_rust_available`-style probes and a real call (matching the
  pattern established in `parser_facade.py` and
  `agent_scan_facade.py`).
- `read_status_from_lines` and `apply_status_update` register their
  Rust adapters as `rust_impl` whenever `sase_core_rs` is importable
  **and** exposes the matching attribute. The previous
  `rust_unavailable="python"` escape hatch is gone — these helpers
  are now classified as shipped Rust operations, so missing bindings
  under `SASE_CORE_BACKEND=rust` raise `RustBackendUnavailableError`
  via the existing dispatcher contract.
- `transition_changespec_status` keeps `rust_unavailable="python"`.
  Phase 4D explicitly does not move the IO-bearing transition off
  Python; Phase 4E will.
- The module docstring is updated to spell out the new Rust-routing
  policy and call out that the line-helper bindings ship in 4D while
  the planner integration waits for 4E.

### Tests (`tests/test_core_facade.py`)

The previous fall-back assertion
(`test_status_facade_rust_without_impl_falls_back_to_python`)
contradicts the new Phase 4D policy and was deleted. The replacement
suite covers:

- `test_status_facade_pure_helpers` (unchanged) — default Python
  backend still produces the same output.
- `test_status_facade_line_helpers_rust_without_binding_raises` —
  installs a fake `sase_core_rs` that exposes neither helper and
  asserts both calls raise `RustBackendUnavailableError` with the
  operation name in the message.
- `test_status_facade_line_helpers_rust_backend_uses_rust_impl` —
  installs a fake module returning sentinel values, sets
  `SASE_CORE_BACKEND=rust`, and asserts both fakes were called with
  the original arguments and that the sentinel values reach the
  caller (proving no silent Python fallback).
- `test_status_facade_line_helpers_dual_run_logs_comparison` — sets
  `SASE_CORE_DUAL_RUN=1` with a fake module that mirrors Python
  output byte-for-byte, asserts each helper produced exactly one
  matched JSONL record under stable operation names, and checks the
  Python result is what the caller sees.
- `test_status_facade_line_helpers_real_extension_parity` — uses
  `pytest.importorskip(RUST_EXTENSION_MODULE_NAME)` so the test
  passes/skips cleanly without `sase_core_rs`. When the extension is
  installed it asserts the Rust binding's output equals
  `read_status_from_lines_python` / `apply_status_update_python`
  byte-for-byte on the standard `_SAMPLE_PROJECT_TEXT` corpus.

A small fake-module helper `_install_fake_status_module` mirrors the
existing `_install_fake_query_module` / `_install_fake_rust_module`
helpers in this file so the new tests follow the same shape as the
Phase 1/2/3 facade tests.

### Documentation (`docs/rust_backend.md`)

- The opening paragraph and the `SASE_CORE_BACKEND` policy section
  add the line helpers to the list of shipped Rust operations and
  drop them from the "intentionally unported" list — leaving
  `transition_changespec_status` (alongside query context/per-row
  evaluation and graph index) as the remaining Python-fallback
  operations.
- The roadmap gains a Phase 4C entry summarising the shipped Rust
  module and PyO3 bindings (which previously was implicit in the
  Phase 4B note) and a Phase 4D entry describing the facade routing
  and dual-run wiring landed here.

## What did not change

- `src/sase/core/status_wire.py` and
  `src/sase/core/status_wire_conversion.py` — Phase 4B contract
  unchanged.
- `src/sase/status_state_machine/transitions.py` and
  `src/sase/status_state_machine/handlers.py` continue to call into
  the facade-level `read_status_from_lines` / `apply_status_update`
  wrappers. With `SASE_CORE_BACKEND=python` (the default) this still
  hits the existing Python implementation; with
  `SASE_CORE_BACKEND=rust` and the binding installed it now hits
  Rust. No transition logic moved.
- The Rust crate (`../sase-core`) — Phase 4D is a Python-side change
  only. No new bindings, no Rust source edits.
- Default backend stays `python`. The line helpers route to Rust
  only under explicit `SASE_CORE_BACKEND=rust` selection.

## Files changed in `sase_100`

- `src/sase/core/status_facade.py` — Rust adapter functions,
  rust_impl registration on the two line helpers, updated module
  docstring; `transition_changespec_status` unchanged in behaviour.
- `tests/test_core_facade.py` — replaced the fall-back assertion
  with the four new line-helper tests described above and a real-
  extension parity test that skips cleanly without `sase_core_rs`.
- `docs/rust_backend.md` — opening paragraph, backend-selection
  paragraph, and roadmap entries for Phase 4C and Phase 4D.
- `plans/202604/rust_backend_phase4_status_machine_phase4d_handoff.md`
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

The default-backend run and the `SASE_CORE_BACKEND=rust` run both
pass on this workspace. The real-extension parity test exercises the
shipped `sase_core_rs.read_status_from_lines` and
`sase_core_rs.apply_status_update` bindings directly when the
extension is installed; otherwise it skips with the standard
`pytest.importorskip` message so a pure-Python checkout is never
blocked.

## Hand-off to Phase 4E

The Phase 4E agent should:

1. Refactor `transition_changespec_status_python` so the in-lock
   pure-decision step is separable from the out-of-lock side
   effects, mirroring the structure already laid down by
   `plan_status_transition_python` in
   `src/sase/core/status_wire_conversion.py`.
2. Register `plan_status_transition` on `status_facade.py`. The
   adapter has the same shape as the line helpers: pull the binding
   from `load_rust_extension()`, marshal the request via
   `status_wire_to_json_dict`, and rehydrate the response through
   `status_plan_from_dict`. The Phase 4C handoff documents the
   binding contract end-to-end; the wire round-trip tests in
   `tests/test_core_status_wire.py` already cover the payload shape.
3. Drop `rust_unavailable="python"` from
   `transition_changespec_status` once the Rust planner is the
   pure-decision step inside it. The IO side effects remain in
   Python — the dispatcher only swaps the planning step. Sibling
   revert results, mentor-flag mutation, atomic write, archive
   moves, timestamp recording, and VCS calls all stay on the host.
4. Wire dual-run for `plan_status_transition` so plan drift surfaces
   in `~/.sase/perf/core_dual_run.jsonl` exactly the way line-helper
   drift does today, **before** any side effects fire (the
   dispatcher already returns the Python plan under dual-run, so
   side-effect dispatch on the Python plan is correct).
5. Keep the line-helper routing in place. Phase 4D's contract
   classifies them as shipped Rust ops; do not regress them to
   Python fallback when wiring the planner.

The line-helper bindings call into `sase_core_rs` with the exact
same positional argument lists as the Python helpers, so any future
adapter or wrapper that wants to bypass dispatch (e.g. for a perf
test) can do so by importing the binding directly — no wire-record
construction is needed for these two helpers.

## Notes for follow-ups

- The dual-run record's `input_hash` for the line helpers is
  computed from the entire `lines` argument via
  `compute_input_hash`, so very large project files will produce
  long-running hashes per call under `SASE_CORE_DUAL_RUN=1`. The
  hash is `sha256` of `repr(lines)` once per call which is cheap
  next to actual list equality between the Python and Rust outputs;
  no special handling needed unless dual-run logs grow unwieldy.
- The line helpers are CPU-light; the Phase 4C handoff explicitly
  decided not to release the GIL for them. If a future profile
  shows `apply_status_update` dominating a hot loop, revisit the
  PyO3 binding before adding a Python-side cache.
- Phase 4D does **not** add a per-operation default-Rust override,
  in line with the Phase 4 plan. The benchmark + decision step
  belongs to Phase 4F once the planner integration is in.
