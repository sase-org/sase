---
create_time: 2026-05-01 00:00:00 -0400
bead_id: sase-1o.7
status: complete
---
# Query Corpus Phase 7 Cleanup Handoff

## Changed

- Removed the product Python batch implementation from `src/sase/core/query_facade.py`.
- Kept `evaluate_query_many(query, changespecs)` as a compatibility API, but it now compiles a temporary Rust query
  corpus and evaluates through `evaluate_query_many_with_corpus`.
- Left the TUI hot path on the Phase 5 cached corpus route. Per-keystroke filtering still avoids `ChangeSpec` to wire
  conversion.
- Kept non-TUI callers (`sase axe`, check cycles, and `sase changespec search`) on the public compatibility wrapper
  rather than migrating them to long-lived corpus ownership. These are one-off or low-frequency surfaces, so the
  temporary corpus cost is acceptable and the API remains stable.
- Renamed the benchmark's Python batch row to `reference_python_batch_evaluate_many`, making it clear that it is a
  benchmark reference and not the shipped product path.
- Renamed the old Rust one-shot benchmark row to `rust_one_shot_diagnostic_evaluate_many`. It remains a direct binding
  diagnostic only and is not a regression-floor anchor.
- Updated the Phase 7 regression adaptor so the persistent query-keystroke anchor still compares against the reference
  Python batch baseline.
- Updated `docs/rust_backend.md` and `sdd/research/202604/rust_core_next_candidates.md` to reflect that query batch
  evaluation has moved to persistent Rust corpora.

## Compatibility Decision

`evaluate_query_many(query, changespecs)` remains available for existing callers. Its behavior is compatibility-only:
it compiles a temporary Rust corpus for the supplied list, compiles the query, evaluates through Rust, and drops the
corpus.

Hot paths should not use this wrapper. Any surface that evaluates multiple queries against the same `ChangeSpec` list
should own a `QueryCorpus` built by `compile_query_corpus(changespecs)` and should invalidate it when the list object's
identity or length changes.

No Python batch compatibility shim remains in product code. The only Python batch evaluator left is the benchmark
reference row in `tests/perf/bench_core_query.py`, where it is used to keep the regression floor comparable to the
Phase 6 gate.

## Verification

```bash
just install
.venv/bin/pytest tests/test_core_facade/test_query.py tests/ace/tui/test_changespec_query_corpus_routing.py tests/perf/phase7/test_phase7_check_regression.py tests/perf/bench_core_query.py::test_bench_core_query_smoke -q
just phase7-perf-check --smoke
just check
```

Results:

- `just install` passed and rebuilt `sase_core_rs` from `../sase-core`.
- Focused pytest passed: 36 passed, 1 deselected.
- Focused pytest after privatizing the Python reference parser passed: 50 passed, 1 deselected.
- `just phase7-perf-check --smoke` passed. The query-corpus anchor measured `persistent_query_keystroke` at 68.79 us
  against a 93.38 us ceiling and a same-run reference Python batch median of 4889.28 us.
- `just check` passed.

`just rust-check` was attempted twice. The plain run first failed because PyO3 selected a Python 3.10 interpreter for an
`abi3-py312` build. Re-running with
`PYO3_PYTHON=/home/bryan/projects/github/sase-org/sase_100/.venv/bin/python PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`
cleared that interpreter issue, but `cargo clippy --workspace --all-targets -- -D warnings` still failed in the clean
`../sase-core` sibling checkout on existing notification-store lints unrelated to this phase:

- `crates/sase_core/src/notifications/store.rs:51` and `:608`: `clippy::incompatible_msrv` for `File::lock_shared` /
  `File::unlock` with MSRV 1.78.
- `crates/sase_core/src/notifications/store.rs:574`: `clippy::suspicious_open_options` for `.create(true)` without an
  explicit truncate/append choice.

No sibling-repo files were changed for this phase.
