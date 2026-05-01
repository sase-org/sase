---
create_time: 2026-05-01 00:00:00 -0400
bead_id: sase-1o.4
status: complete
---
# Query Corpus Phase 4 Performance Handoff

## Changed

- Extended `tests/perf/bench_core_query.py` with persistent query-corpus
  benchmark rows:
  - `python_batch_evaluate_many`: current Python batch baseline.
  - `rust_legacy_direct_evaluate_many`: old one-shot Rust binding that rebuilds
    wire/corpus state per call.
  - `rust_persistent_corpus_compile`: product-visible corpus compilation cost
    through `compile_query_corpus(changespecs)`.
  - `rust_persistent_fully_compiled_evaluate_many`: corpus and query compiled
    outside the timed loop.
  - `rust_persistent_query_keystroke_evaluate_many`: corpus compiled outside
    the timed loop; query compile plus evaluate inside the timed loop.
- Added a `gate` block to the benchmark JSON so the Phase 4 routing decision is
  machine-readable.
- Added a home-tree workload to the CLI path. It runs by default outside CI,
  can be skipped with `--skip-home-tree`, and remains off for direct in-process
  harness calls used by the Phase 7 floor.
- Updated `tests/perf/phase7/phase7b_adaptors.py` so
  `evaluate_query_many` summaries expose `persistent_query_keystroke` as a
  distinct candidate scenario instead of conflating it with the public
  `query_facade.evaluate_query_many` compatibility path.
- Updated `tests/perf/phase7_check_regression.py` so future
  `evaluate_query_many.synthetic_<N>_specs` anchors automatically run the
  matching query harness sizes.
- Updated `tests/perf/baselines/phase7_regression_floor.json` to document that
  the persistent query-corpus row is exposed for future anchoring but is not a
  current floor anchor.

## Artifact

- `plans/202604/perf_artifacts/query_corpus_phase4_baseline.json`

Captured with:

```bash
just bench-query --runs 20 --warmup 3 --spec-sizes 100,1000,10000 --output plans/202604/perf_artifacts/query_corpus_phase4_baseline.json
```

## Medians

| Workload | Specs | Python batch ms | Persistent keystroke ms | Speedup | Corpus compile ms | Legacy one-shot ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `synthetic_100_specs` | 100 | 0.373 | 0.00978 | 38.2x | 6.58 | 4.09 |
| `synthetic_1000_specs` | 1,000 | 3.750 | 0.0664 | 56.5x | 76.17 | 43.57 |
| `synthetic_10000_specs` | 10,000 | 56.564 | 0.775 | 72.9x | 816.92 | 473.85 |
| `home_tree` | 1,986 | 5.093 | 0.0930 | 54.8x | 49.14 | 28.43 |

The fully compiled Rust evaluate row is smaller again, but the gate uses the
product-relevant query-keystroke row because Phase 5 will compile a new query
for each edit while reusing the cached corpus.

## Gate Result

Passed.

- `synthetic_100_specs`: required not slower than Python; measured 38.2x
  faster.
- `synthetic_1000_specs`: required at least 2x faster; measured 56.5x faster.
- `synthetic_10000_specs`: required at least 2x faster; measured 72.9x faster.
- Home-tree workload also passed on the local 1,986-spec corpus at 54.8x faster.

Phase 5 is allowed to flip TUI product filtering to
`evaluate_query_many_with_corpus(...)` when its list-identity cache contract is
implemented. The old one-shot Rust binding remains a diagnostic benchmark row
only; it is still much slower than Python because it rebuilds wire/corpus state
per call.

## Verification

- `just install`
- `.venv/bin/pytest tests/perf/bench_core_query.py tests/perf/phase7/test_phase7_check_regression.py -q`
- `.venv/bin/python -m ruff check tests/perf/bench_core_query.py tests/perf/phase7/phase7b_adaptors.py tests/perf/phase7_check_regression.py`
- `just bench-query --runs 20 --warmup 3 --spec-sizes 100,1000,10000 --output plans/202604/perf_artifacts/query_corpus_phase4_baseline.json`
- `just phase7-perf-check --smoke`
