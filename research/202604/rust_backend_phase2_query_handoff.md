---
create_time: 2026-04-29 04:00:00
plan: ../../plans/202604/rust_backend_phase2_query.md
bead: sase-17
---
# Rust Backend Phase 2 Query — Handoff & Rollout Decision

## Decision: keep the Rust query backend opt-in; do NOT flip the default. The Python batch path is the actual product win from Phase 2.

## Verification summary (sase-17.6)

`sase_100`:
- `just install` — clean.
- `just rust-install` — builds `sase_core_rs` against this checkout's venv (CPython 3.14 needs `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` until pyo3 ships a 3.14 release; functional impact is none).
- Focused `pytest -k "core_query or core_golden or core_facade or query"` — 327 passed, 1 skipped.
- `just check` — all gates pass (fmt, ruff, mypy, pyvision, test).

`../sase-core`:
- `cargo fmt --all -- --check` — clean.
- `cargo clippy --workspace --all-targets -- -D warnings` — clean.
- `cargo test --workspace` — 124 tests pass (108 lib + 3 + 2 + 11 integration).

## Benchmark results (`just bench-query`, runs=20, warmup=3)

Query: `'"feature" OR status:Ready'`. Numbers are median ms; lower is better.

### parse_only

| Scenario | median ms |
|---|---:|
| python_direct_parse | 0.009 |
| python_facade_parse | 0.011 |
| **rust_direct_parse** | **0.004** |
| rust_facade_parse | 0.015 |

Rust is faster than Python at direct parse (~2.3x), but the facade overhead (load_rust_extension lookup, dispatch, AST projection through `query_expr_wire_from_dict`) wipes the win.

### parse + evaluate

| Specs | python_parse_and_evaluate | python_batch_evaluate_many | rust_direct_evaluate_many | rust_facade_evaluate_many | dual_run |
|---:|---:|---:|---:|---:|---:|
| 100 | 0.475 | 0.376 | 3.97 | 6.59 | 7.97 |
| 1000 | 4.51 | 3.54 | 40.98 | 70.77 | 81.93 |
| 10000 | 63.68 | 52.08 | 413.18 | 771.10 | 918.66 |

## Applying the >=2x research go gate

The research plan's go gate: "Rust should be at least 2x faster for large lists after FFI/conversion cost before considering a default flip."

At 10k specs, **Rust facade is 14.8x slower** than the Python batch facade and **12.1x slower** than the per-row Python path. **Rust does not clear the gate — it is decisively below it.**

The conversion cost dominates: `[to_json_dict(changespec_to_wire(cs)) for cs in changespecs]` materializes a fully rectangular dict tree per spec, then PyO3+serde re-deserializes that tree on the Rust side, before any query work runs. For 10k specs the Rust evaluator is doing more allocator/serde work than the Python evaluator does total work — and Python's evaluator already benefits from `QueryEvaluationContext` caches built once per list.

Phase 1 (parser) cleared the gate: `bench-core` shows `rust_facade` 2.6x faster than `python_facade` at 200 specs, because parse work happens *inside* Rust on bytes — no Python→dict conversion in the hot path.

## What the product actually got from Phase 2

The win is the Python batch path itself (`evaluate_query_many` with the default backend). Versus the previous per-row `evaluate_query_with_context` loop, the Python batch is:

| Specs | per-row | batch | improvement |
|---:|---:|---:|---:|
| 100 | 0.475 ms | 0.376 ms | 21% faster |
| 1000 | 4.51 ms | 3.54 ms | 21% faster |
| 10000 | 63.68 ms | 52.08 ms | 18% faster |

That's a real, durable improvement to TUI list refresh (`actions/changespec/_loading.py`), `axe chop run`, `sase search`, and `axe check_cycles` (Phase 2E call sites), and it's pure Python — no conditional Rust dependency, no FFI.

## Recommendation for Phase 3 and beyond

1. **Keep `SASE_CORE_BACKEND` query routing optional**; do not change the default. The Python implementation is the production path.
2. **Do not invest further in Rust query evaluation** until the FFI conversion cost is addressed at the source. Two paths would unblock it, neither cheap:
   - Cache the wire-dict snapshot of `ChangeSpecWire` on `ChangeSpec` so we pay the conversion once at parse time, not per query refresh.
   - Move `ChangeSpec` itself behind the wire shape so query evaluation reuses the same buffer the parser already filled.
3. **Phase 3 (agent / artifact filesystem scan) is the right next bottleneck** — the work happens entirely in Rust on filesystem bytes, mirroring Phase 1's win profile, not Phase 2's loss profile.
4. The `evaluate_query_many` batch facade should stay because it's a real product improvement; the Rust binding stays because it makes parity testing cheap and it's already paid for.

## Notes for future maintainers

- `tests/perf/bench_core_query.py` now reports Rust scenarios when `sase_core_rs` is importable. Re-run `just bench-query` after any conversion-cost work to see whether the gap closes.
- `SASE_CORE_DUAL_RUN=1 evaluate_query_many` is ~17.6x slower than the default Python path at 10k specs (918 ms vs 52 ms). Useful for diagnosis, never for production.
- The Rust crate's `cargo test --workspace` covers Python parity via the golden corpus fixture; if the Python golden corpus changes, regenerate `sase_100/tests/test_core_query_golden.py` snapshots and copy the JSON fixture into `../sase-core/crates/sase_core/tests/fixtures/`.
