# Phase 8B Handoff: Resolve The `evaluate_query_many` Regression

Bead: `sase-1f.2`. Plan: `plans/202604/rust_backend_phase8.md`. Phase 8B is the performance-remediation pass for
`evaluate_query_many`, the one Phase 7 surface that regressed when routed through the dispatched Rust path. Phase 8B
must either land an amortised Rust path that meets the perf gate or formally reclassify the operation as
deferred/unported. After reproducing the Phase 7 regression on this workspace and measuring the achievable Rust
path with no in-window wire conversion, **Phase 8B takes the acceptable-fallback exit and reclassifies
`evaluate_query_many` as deferred/unported**. The Python batch implementation stays as the authoritative path; the
facade's Rust adapter is removed; later subphases (8D / 8F) will remove only the dispatcher plumbing around it.

## Outcome: deferred/unported

The dispatched Rust path is 6-9× slower than the optimised Python batch path even with the wire conversion already
done outside the timed window. The Phase 8B work scope (`src/sase/core/query_facade.py` and Python-side wire helpers)
cannot close that gap; the residual cost is PyO3+serde rebuilding `ChangeSpecWire` from the spec dicts inside Rust on
every call. Closing the gap would require a persistent corpus handle inside `sase_core_rs` (so a list of specs can
be uploaded once and queried many times), which is a Rust/PyO3 surface change well outside the Phase 8B write scope.

The plan's acceptable fallback path applies: keep `_evaluate_query_many_python` as the authoritative implementation,
remove the Rust adapter from the facade so `sase_core_rs.evaluate_query_many` is no longer reachable from product
code, and document the deferral so 8C / 8D / 8F do not reintroduce the routed Rust path.

## What landed

- `src/sase/core/query_facade.py` — `evaluate_query_many` now uses
  `dispatch(operation="evaluate_query_many", python_impl=_evaluate_query_many_python, rust_unavailable="python", ...)`
  with no `rust_impl=`. The `_rust_evaluate_query_many_impl` adapter and the wire-conversion imports it required
  (`to_json_dict`, `changespec_to_wire`) are deleted. Module docstring rewritten to explain the Phase 8B deferral
  and what would unblock a future port.
- `tests/test_core_facade/test_backend_contract.py` — moves `evaluate_query_many` from `SHIPPED_OPERATIONS` to
  `UNPORTED_OPERATIONS`. `test_facade_inventory_matches_expected_classification` continues to walk the facade
  modules and validates that the new classification matches the only `dispatch(operation="evaluate_query_many", ...)`
  call site.
- `tests/test_core_facade/test_query.py` — drops the four Rust/dual-run tests that pinned the Phase 6/7 contract
  (`test_evaluate_query_many_rust_backend_uses_rust_impl`,
  `test_evaluate_query_many_rust_backend_forwards_null_mentor_timestamp`,
  `test_evaluate_query_many_rust_backend_missing_binding_raises_cleanly`,
  `test_evaluate_query_many_dual_run_logs_comparison`). Replaces them with two contract tests that pin the new
  deferred behaviour: under `SASE_CORE_BACKEND=rust` the facade ignores any registered
  `sase_core_rs.evaluate_query_many` binding and runs the Python batch implementation; under
  `SASE_CORE_DUAL_RUN=1` no comparison record is written.
- `tests/parity/dual_run_parity.py` — drops `evaluate_query_many` from `SHIPPED_OPERATIONS` so the dual-run parity
  gate stops requiring a record for the deferred surface. The harness still exercises `_exercise_query()` for
  `parse_query`; the trailing `query_facade.evaluate_query_many(query, specs)` call is intentionally retained
  because it now runs the Python path silently and provides a coverage anchor for the deferred routing.
- `plans/202604/perf_artifacts/rust_backend_phase8b_evaluate_query_many_after_deferral.json` — fresh
  bench_core_query report (20 runs / 3 warmup, spec sizes 100 and 1000) captured after the facade change. Numbers
  reproduced below; the file is the canonical evidence trail referenced by 8C-8F.
- `plans/202604/rust_backend_phase8_phase8b_handoff.md` — this file.

No code changes were made under `../sase-core/` (no Rust/PyO3 binding work was needed since deferral, by definition,
does not touch the binding) or to the Phase 7 regression floor (`tests/perf/baselines/phase7_regression_floor.json`).
The floor never anchored `evaluate_query_many`; the surface stays excluded.

## Reproduction of the Phase 7 regression

Local reproduction on this workspace (`sase_103`, on `master @ aaea63f0` immediately after `just install` and before
the facade change), running `bench_core_query` with the smallest stable workload from the Phase 7 artifacts:

```
.venv/bin/python -m tests.perf.bench_core_query --runs 5 --warmup 2 --spec-sizes 100,1000
```

| Workload | scenario                       | min_ms | median_ms | p95_ms |
| -------- | ------------------------------ | ------ | --------- | ------ |
| 100      | python_batch_evaluate_many     |  0.366 |   0.367   |  0.370 |
| 100      | rust_direct_evaluate_many      |  4.029 |   4.032   |  4.033 |
| 100      | rust_facade_evaluate_many      |  6.595 |   6.659   |  9.273 |
| 100      | dual_run_evaluate_many         |  7.923 |   8.051   |  8.324 |
| 1000     | python_batch_evaluate_many     |  3.658 |   3.683   |  3.922 |
| 1000     | rust_direct_evaluate_many      | 41.266 |  41.777   | 45.299 |
| 1000     | rust_facade_evaluate_many      | 72.285 |  73.908   | 84.642 |
| 1000     | dual_run_evaluate_many         | 84.178 |  87.697   | 96.948 |

The "direct" scenario is the Rust path with the wire dicts pre-computed and reused across runs; even there Rust
is ≥10× slower than the Python batch path. Routing through the facade adds another ~50% on top. This matches the
Phase 7B finding that per-call wire conversion dominates, and extends it: even without per-call wire conversion the
Rust evaluator pays serde dict→`ChangeSpecWire` deserialization on every call, and that fixed-per-call cost is what
makes the gate unbeatable from inside the Phase 8B scope.

## After-deferral benchmark

Post-change reproduction with the same harness (20 runs / 3 warmup), saved to
`plans/202604/perf_artifacts/rust_backend_phase8b_evaluate_query_many_after_deferral.json`:

| Workload | scenario                       | min_ms | median_ms | p95_ms |
| -------- | ------------------------------ | ------ | --------- | ------ |
| 100      | python_batch_evaluate_many     |  0.373 |   0.375   |  0.384 |
| 100      | rust_direct_evaluate_many      |  3.992 |   4.117   |  4.160 |
| 100      | rust_facade_evaluate_many      |  0.381 |   0.383   |  0.407 |
| 100      | dual_run_evaluate_many         |  0.381 |   0.384   |  0.410 |
| 1000     | python_batch_evaluate_many     |  3.666 |   3.700   |  4.264 |
| 1000     | rust_direct_evaluate_many      | 41.334 |  42.696   | 43.799 |
| 1000     | rust_facade_evaluate_many      |  3.589 |   3.638   |  3.950 |
| 1000     | dual_run_evaluate_many         |  3.642 |   3.816   |  4.324 |

Reading: `rust_facade_evaluate_many` (sets `SASE_CORE_BACKEND=rust` and calls the facade) and
`dual_run_evaluate_many` (sets `SASE_CORE_DUAL_RUN=1` and calls the facade) now match the `python_batch_evaluate_many`
median to within measurement noise. The deferral is doing its job: every product caller is on the Python batch path
regardless of env var. `rust_direct_evaluate_many` continues to call `rust_module.evaluate_query_many` directly with
pre-computed wire dicts and is reported as historical evidence of where the Rust path stands today; it has no
product caller after Phase 8B.

## Updated Phase 8 operation disposition

This supersedes the corresponding rows in the Phase 8A handoff. Move `evaluate_query_many` out of the "blocked"
section and into the "intentionally unported" section.

### Direct Python because intentionally unported (Phase 8C target list)

| Operation                       | Facade                                  | Direct Python target                          |
| ------------------------------- | --------------------------------------- | --------------------------------------------- |
| `build_query_context`           | `src/sase/core/query_facade.py`         | `build_query_context_python`                  |
| `evaluate_query`                | `src/sase/core/query_facade.py`         | `evaluate_query_python`                       |
| `evaluate_query_with_context`   | `src/sase/core/query_facade.py`         | `evaluate_query_with_context_python`          |
| `evaluate_query_many` (8B)      | `src/sase/core/query_facade.py`         | `_evaluate_query_many_python`                 |
| `build_changespec_graph_index`  | `src/sase/core/graph_index_facade.py`   | `build_changespec_graph_index_python`         |
| `transition_changespec_status`  | `src/sase/core/status_facade.py`        | `transition_changespec_status_python`        |

The "Temporarily blocked by performance remediation" section is now empty for Phase 8B's scope.

## Verification

```
just install
.venv/bin/python -m pytest tests/test_core_facade/test_query.py tests/test_core_facade/test_backend_contract.py
.venv/bin/python -m pytest tests/test_core_golden.py tests/test_core_dual_run.py tests/test_core_backend.py tests/test_core_parity_smoke.py
just parity-check
.venv/bin/python -m tests.perf.bench_core_query --runs 20 --warmup 3 --spec-sizes 100,1000 \
    --output plans/202604/perf_artifacts/rust_backend_phase8b_evaluate_query_many_after_deferral.json
just check
```

All commands ran clean except `just phase7-perf-check`, which fails on
`apply_status_update.golden_myproj_pure.apply_status_update` (rust=9.15us vs ceiling=8.12us). This is the sub-50µs
status-helper noise the Phase 7F handoff already documented as a known measurement caveat — Phase 7E excluded
status helpers from the floor as `must_beat_python=False` guards, and the noise lives at the same scale as the
operation itself. The failure is **not caused by Phase 8B** (the Phase 8B change is confined to
`src/sase/core/query_facade.py` and its tests, and `apply_status_update` runs through `status_facade.py`).
Phase 8E / 8F own the re-measurement and reclassification of these tiny normalisers.

## Hand-off notes for Phase 8C and beyond

- **8C / 8D**: `evaluate_query_many` is now in the same bucket as `build_query_context`, `evaluate_query`, etc. Phase
  8C (the unported-facade rewire pass) should switch the dispatch call to a direct call into
  `_evaluate_query_many_python` once the dispatcher is being torn down. **Do not delete `_evaluate_query_many_python`
  in Phase 8D's "delete clear-win Python halves" pass** — the Phase 8B handoff is the explicit justification for
  keeping it. Phase 8D should remove only the dispatcher wrapping for this surface, mirroring the rewire it does for
  `build_query_context` and friends.
- **8F (dispatcher / dual-run / CI cleanup)**: When Phase 8F deletes `tests/parity/dual_run_parity.py`, the trailing
  `query_facade.evaluate_query_many` call inside `_exercise_query` goes with it; nothing else needs to be unwound
  for this surface. The `_rust_evaluate_query_many_impl` adapter is already gone; the unused
  `to_json_dict` / `changespec_to_wire` import lines were removed in this subphase.
- **8G (close-out / docs)**: `docs/rust_backend.md` should add `evaluate_query_many` to the "intentionally
  unported" or "Python-owned host logic" list with a one-line justification ("PyO3+serde dict→wire deserialization
  per call exceeds the optimised Python batch path; future port requires a persistent Rust corpus handle"). This
  is the only language change Phase 8G needs for `evaluate_query_many` — the post-Phase-8 rollback story is
  unchanged because the operation never ran on Rust in production.
- **Future port**: A genuinely amortised Rust path is still possible — it just needs a `sase_core_rs` PyO3 surface
  that takes a list of `ChangeSpecWire` once and returns a callable / handle that can be queried multiple times.
  The benchmark harness's `rust_direct_evaluate_many` row is the right anchor to compare against; the optimised
  Python batch (`python_batch_evaluate_many`) is the gate to beat.
