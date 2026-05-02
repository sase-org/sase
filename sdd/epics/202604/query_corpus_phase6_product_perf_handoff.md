---
create_time: 2026-05-01 00:00:00 -0400
bead_id: sase-1o.6
status: complete
---
# Query Corpus Phase 6 Product Perf Handoff

## Changed

- Re-ran the query benchmark after Phase 5 TUI product routing and captured:
  - `plans/202604/perf_artifacts/query_corpus_phase6_product_perf.json`
- Extended `tests/perf/bench_tui_trace.py` so query-change scenarios update
  both `query_string` and `parsed_query`. The persistent-corpus product route
  evaluates `query_string`, so the old trace harness was no longer timing the
  intended query edit.
- Added a repeated-query-edit section to the TUI trace harness. It reuses one
  loaded ChangeSpec list and applies multiple query strings to exercise the
  product cached-corpus route.
- Captured TUI trace artifacts:
  - `plans/202604/perf_artifacts/query_corpus_phase6_tui_trace_summary.json`
  - `plans/202604/perf_artifacts/query_corpus_phase6_tui_trace.jsonl`
  - `plans/202604/perf_artifacts/query_corpus_phase6_tui_jk.jsonl`
- Added the product persistent-corpus query-keystroke row to the Phase 7
  regression floor:
  - `evaluate_query_many.synthetic_1000_specs.persistent_query_keystroke`
- Updated the floor checker so that this Rust candidate row compares against
  the Python batch baseline row (`facade`) instead of looking for a same-named
  Python scenario.

The legacy one-shot Rust row remains a benchmark diagnostic only. It is not a
floor anchor.

## Query Benchmark

Captured with:

```bash
just bench-query --runs 20 --warmup 3 --spec-sizes 100,1000,10000 --output plans/202604/perf_artifacts/query_corpus_phase6_product_perf.json
```

| Workload | Python batch ms | Persistent keystroke ms | Speedup | Corpus compile ms | Legacy one-shot ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| `synthetic_100_specs` | 0.376 | 0.0101 | 37.0x | 6.73 | 4.26 |
| `synthetic_1000_specs` | 3.999 | 0.0667 | 60.0x | 67.78 | 41.42 |
| `synthetic_10000_specs` | 57.441 | 0.779 | 73.7x | 783.14 | 461.20 |
| `home_tree` | 5.173 | 0.0963 | 53.7x | 44.39 | 28.51 |

Compared with the Phase 4 pre-routing benchmark artifact, the product
persistent-keystroke path stayed consistent:

| Workload | Phase 4 speedup | Phase 6 speedup |
| --- | ---: | ---: |
| `synthetic_100_specs` | 38.2x | 37.0x |
| `synthetic_1000_specs` | 56.5x | 60.0x |
| `synthetic_10000_specs` | 72.9x | 73.7x |
| `home_tree` | 54.8x | 53.7x |

## TUI Trace

Captured with:

```bash
.venv/bin/python -m tests.perf.bench_tui_trace \
  --output plans/202604/perf_artifacts/query_corpus_phase6_tui_trace_summary.json \
  --trace-path plans/202604/perf_artifacts/query_corpus_phase6_tui_trace.jsonl \
  --perf-path plans/202604/perf_artifacts/query_corpus_phase6_tui_jk.jsonl
```

The trace includes `changespec.filter` spans across initial load, query change,
the repeated-query-edit sequence, and reset. These timings are end-to-end TUI
filter spans, so they include non-query work such as status-map/context setup
and display refresh coupling; the core query evaluator cost is represented by
the benchmark table above.

| ChangeSpecs | `changespec.filter` n | p50 ms | p95 ms | max ms | Repeated query edits wall ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 12 | 49.42 | 134.56 | 182.28 | 1960.63 |
| 500 | 12 | 51.66 | 63.47 | 73.98 | 717.76 |
| 2000 | 13 | 48.40 | 53.88 | 54.99 | 543.14 |

## Regression Floor

Added one floor anchor at `synthetic_1000_specs`, which is the stable mid-size
product query workload. The committed baseline values are from the Phase 6
capture:

- Python batch median: 3.998827 ms.
- Persistent query-keystroke median: 0.066702 ms.
- Required checks: Rust median must remain under the 1.40x absolute ceiling and
  must beat the same-run Python batch baseline.

`just phase7-perf-check` passes with the new anchor. The new row measured
66.64 us against a 93.38 us ceiling and a same-run Python median of 4094.50 us.

## Cleanup Decision

The TUI product route is safe to keep on the persistent Rust corpus path, and
the regression floor now protects that route. Do not delete
`_evaluate_query_many_python` blindly in Phase 7 yet: Phase 5 identified
non-TUI callers still using the compatibility Python batch path
(`src/sase/axe/check_cycles.py`, `src/sase/axe/cli.py`, and
`src/sase/main/search_handler.py`). Phase 7 should either migrate those callers
to an explicit corpus path or keep a documented compatibility wrapper.

## Verification

```bash
just install
.venv/bin/pytest -m slow tests/perf/bench_tui_trace.py::test_baseline_smoke -q
.venv/bin/pytest -m slow tests/perf/bench_core_query.py::test_bench_core_query_smoke -q
.venv/bin/pytest tests/perf/phase7/test_phase7_check_regression.py -q
.venv/bin/ruff check tests/perf/phase7_check_regression.py tests/perf/phase7/test_phase7_check_regression.py tests/perf/bench_tui_trace.py
just bench-query --runs 20 --warmup 3 --spec-sizes 100,1000,10000 --output plans/202604/perf_artifacts/query_corpus_phase6_product_perf.json
.venv/bin/python -m tests.perf.bench_tui_trace --output plans/202604/perf_artifacts/query_corpus_phase6_tui_trace_summary.json --trace-path plans/202604/perf_artifacts/query_corpus_phase6_tui_trace.jsonl --perf-path plans/202604/perf_artifacts/query_corpus_phase6_tui_jk.jsonl
just phase7-perf-check
```
