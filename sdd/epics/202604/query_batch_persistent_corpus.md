---
create_time: 2026-04-30 22:44:03
bead_id: sase-1o
status: done
prompt: sdd/prompts/202604/query_batch_persistent_corpus.md
---
# Query Batch Persistent Corpus Migration Plan

## Context

`sdd/research/202604/rust_core_next_candidates.md` recommends re-porting ChangeSpec query batch evaluation to Rust only if
the FFI shape changes from "deserialize every `ChangeSpecWire` dict on every filter keystroke" to "compile the corpus
once, then evaluate many queries against the persistent corpus." Phase 8B already proved the old routed Rust
`evaluate_query_many(query, spec_dicts)` path was a regression, so this migration must keep the Python batch path until
the persistent-handle route beats it on the regression floor.

Current state:

- `src/sase/core/query_facade.py` calls Rust only for `parse_query`; `evaluate_query_many` deliberately calls
  `_evaluate_query_many_python`.
- `src/sase/ace/tui/actions/changespec/_loading.py` calls `evaluate_query_many(self.query_string, changespecs)` on every
  CL filter refresh.
- `../sase-core/crates/sase_core/src/query/evaluator.rs` already has `QueryProgram`, `QueryEvaluationContext`, and pure
  `evaluate_query_many(&QueryProgram, &[ChangeSpecWire])`, but context and wire deserialization are rebuilt per call.
- `../sase-core/crates/sase_core_py/src/lib.rs` exposes only the old one-shot PyO3
  `evaluate_query_many(query, specs: list[dict])`.

The implementation should be split into the phases below. Each phase is intended for a distinct agent instance and
should leave a short handoff note under `plans/202604/` describing what changed, what was verified, and what remains.

## Design Target

Add a persistent Rust corpus and compiled query handle:

- Pure Rust:
  - `QueryCorpus` owns `Vec<ChangeSpecWire>` plus reusable derived data such as lowercased names, parent lookup, base
    statuses, project names, sibling bases, searchable text, and lowercase searchable text.
  - `QueryProgram` stays the compiled query representation.
  - `evaluate_query_many_in_corpus(program: &QueryProgram, corpus: &QueryCorpus) -> Vec<bool>` performs one batch
    evaluation without rebuilding the corpus maps.
  - Query-specific mutable state, especially ancestor memoization by searched ancestor value, stays per evaluation call
    so a corpus can be reused safely across many different queries.
- PyO3:
  - `compile_corpus(specs: list[dict]) -> QueryCorpusHandle`.
  - `compile_query(query: str) -> QueryProgramHandle`.
  - `evaluate_many(program: QueryProgramHandle, corpus: QueryCorpusHandle) -> list[bool]`.
  - Keep the legacy `evaluate_query_many(query, specs)` binding as a historical/direct benchmark row until cleanup.
- Python:
  - Add a small `query_corpus_facade` or equivalent query-facade extension that converts `ChangeSpec` objects to wire
    dicts once per `_all_changespecs` list identity, owns the Rust corpus handle, and evaluates new query strings with
    the persistent handle.
  - The TUI cache invalidates when the `changespecs` list object changes. A stale handle must be detected in tests by
    checking the cached list id and expected corpus length before use.

## Phase 1: Pure Rust Corpus Model

Owner scope:

- `../sase-core/crates/sase_core/src/query/`
- `../sase-core/crates/sase_core/src/lib.rs`
- Rust tests under `../sase-core/crates/sase_core/tests/`
- Handoff: `plans/202604/query_corpus_phase1_rust_core_handoff.md`

Work:

1. Add `QueryCorpus` in the pure Rust crate, separate from PyO3.
2. Move reusable per-corpus work out of `QueryEvaluationContext::build()`: name lookup, status normalization,
   project-dir name, sibling base, searchable text, and lowercase searchable text.
3. Keep ancestor memoization as evaluation-call state, not corpus state.
4. Add `evaluate_query_many_in_corpus(&QueryProgram, &QueryCorpus) -> Vec<bool>`.
5. Preserve the existing `evaluate_query_many(&QueryProgram, &[ChangeSpecWire])` API by implementing it as
   `QueryCorpus::new(specs.to_vec())` plus `evaluate_query_many_in_corpus(...)`, so existing Rust callers and tests keep
   compiling.
6. Extend Rust parity tests for the golden query matrix, ancestor cycles, repeated evaluation against one corpus, and
   different queries against the same corpus.

Exit criteria:

- `cargo test --workspace` passes in `../sase-core`.
- Existing Rust query parity tests still pass without Python changes.
- Handoff documents any intentional behavior-preserving refactors in the evaluator.

## Phase 2: PyO3 Persistent Handles

Owner scope:

- `../sase-core/crates/sase_core_py/src/lib.rs`
- `../sase-core/crates/sase_core_py/Cargo.toml` only if needed
- Rust/PyO3 tests in `../sase-core`
- Handoff: `plans/202604/query_corpus_phase2_pyo3_handoff.md`

Work:

1. Add `#[pyclass]` handle types for the corpus and compiled query program.
2. Expose `compile_corpus`, `compile_query`, and `evaluate_many` through the `sase_core_rs` module.
3. Convert Python spec dicts to `ChangeSpecWire` only inside `compile_corpus`.
4. Release the GIL during corpus construction after dict conversion where practical, and during evaluation.
5. Return Python `ValueError` for query compile errors using the existing `query_error_to_pyerr` path.
6. Add PyO3-level tests that:
   - compile one corpus and evaluate multiple queries;
   - compile one query and evaluate multiple corpora;
   - verify length and result parity with the legacy one-shot binding;
   - reject wrong handle types with clear errors.

Exit criteria:

- `cargo test --workspace` passes.
- `sase_core_rs` exposes all three new bindings after `just rust-install`.
- Legacy `sase_core_rs.evaluate_query_many` still exists for benchmark comparison.

## Phase 3: Python Facade And Cache Contract

Owner scope:

- `src/sase/core/query_facade.py`
- New `src/sase/core/query_corpus_facade.py` if keeping the handle API separate is cleaner
- `src/sase/core/wire_conversion.py` only for reusable conversion helpers
- `tests/test_core_facade/test_query.py`
- `tests/test_core_facade/_helpers.py`
- Handoff: `plans/202604/query_corpus_phase3_python_facade_handoff.md`

Work:

1. Add a Python wrapper dataclass around the Rust corpus handle containing: source list id, expected length, and the
   Rust handle.
2. Add `compile_query_corpus(changespecs)` that converts `ChangeSpec` objects to `ChangeSpecWire` JSON dicts once and
   calls `sase_core_rs.compile_corpus`.
3. Add `evaluate_query_many_with_corpus(query, corpus)` that calls `sase_core_rs.compile_query` and
   `sase_core_rs.evaluate_many`.
4. Keep public `evaluate_query_many(query, changespecs)` on the existing Python batch path during this phase.
5. Add tests with fake `sase_core_rs` bindings proving:
   - corpus compilation performs one conversion pass;
   - evaluation does not call legacy `evaluate_query_many`;
   - a forced-stale corpus wrapper raises a clear error or refuses evaluation before returning mismatched results;
   - missing/stale new bindings fail cleanly through `require_rust_binding`.

Exit criteria:

- Focused Python tests pass: `pytest tests/test_core_facade/test_query.py`
- No TUI product path uses the new corpus yet.
- Handoff states the exact invalidation contract the TUI phase must honor.

## Phase 4: Benchmark Harness And Regression Floor

Owner scope:

- `tests/perf/bench_core_query.py`
- `tests/perf/phase7/phase7b_adaptors.py`
- `tests/perf/phase7_check_regression.py`
- `tests/perf/baselines/phase7_regression_floor.json`
- `plans/202604/perf_artifacts/`
- Handoff: `plans/202604/query_corpus_phase4_perf_handoff.md`

Work:

1. Add benchmark scenarios that separate:
   - Python batch baseline;
   - legacy Rust one-shot direct binding;
   - Rust corpus compile cost;
   - Rust persistent-corpus evaluation with corpus and query compiled outside the timed loop;
   - Rust persistent-corpus query-keystroke path with only query compile plus evaluate inside the timed loop.
2. Keep synthetic sizes `100`, `1000`, and `10000`.
3. Add a home-tree workload when available, but make it skippable in CI and explicit in the report.
4. Update Phase 7 adaptor/floor plumbing so the persistent corpus path can become an anchor only after it clears the
   gate.
5. Capture a report under `plans/202604/perf_artifacts/query_corpus_phase4_baseline.json`.

Gate:

- Persistent corpus query-keystroke path must be at least 2x faster than `_evaluate_query_many_python` on
  `synthetic_1000` and `synthetic_10000`.
- It must not be slower than Python on `synthetic_100`.
- Home-tree results should be reported; failure there blocks product routing unless the handoff explains why the fixture
  is not representative.

Exit criteria:

- `just bench-query --runs 20 --warmup 3 --spec-sizes 100,1000,10000 --output ...` produces the new rows.
- `just phase7-perf-check --smoke` still works.
- Handoff includes the measured medians and whether Phase 5 is allowed to flip product routing.

## Phase 5: TUI Product Routing And List-Identity Invalidation

Owner scope:

- `src/sase/ace/tui/actions/_state_init.py`
- `src/sase/ace/tui/actions/changespec/_loading.py`
- Focused TUI tests under `tests/ace/` and `tests/ace/tui/`
- Handoff: `plans/202604/query_corpus_phase5_tui_routing_handoff.md`

Prerequisite:

- Phase 4 handoff says the persistent corpus path cleared the gate.

Work:

1. Add TUI state for the cached query corpus wrapper and the `_all_changespecs` list id it was built from.
2. Build or replace the corpus when `_apply_changespecs()` or `_apply_reloaded_changespecs()` receives a different list
   object.
3. In `_filter_changespecs_impl`, use `evaluate_query_many_with_corpus(self.query_string, cached_corpus)` when the cache
   matches the incoming `changespecs` list id.
4. Keep a defensive fallback to `_evaluate_query_many_python` only if the Phase 4 handoff did not authorize default
   routing; otherwise fail loudly on missing required Rust bindings.
5. Add tests for initial load, reload invalidation, saved-query fallback, hide-submitted/hide-reverted counts, and a
   forced stale handle.

Exit criteria:

- Focused tests for query facade and changespec loading pass.
- The TUI filter path performs no per-keystroke `ChangeSpec -> wire dict` conversion.
- Handoff identifies any non-TUI callers still using the old one-shot `evaluate_query_many`.

## Phase 6: Product Perf Verification And Floor Anchor

Owner scope:

- `tests/perf/bench_tui_trace.py` if needed
- `tests/perf/baselines/phase7_regression_floor.json`
- `plans/202604/perf_artifacts/`
- Handoff: `plans/202604/query_corpus_phase6_product_perf_handoff.md`

Work:

1. Re-run the query benchmark after TUI routing.
2. Capture a TUI trace for `_filter_changespecs` / `changespec.filter` over repeated query edits.
3. Add the persistent corpus query path to the regression floor if it clears the gate consistently.
4. Preserve the legacy one-shot Rust row as a non-product diagnostic, not a floor anchor.

Exit criteria:

- `just phase7-perf-check` passes with the new floor entry.
- Handoff contains before/after filter timings and states whether cleanup can delete the Python batch implementation.

## Phase 7: Cleanup, Documentation, And Deletion Decision

Owner scope:

- `src/sase/core/query_facade.py`
- `src/sase/core/query_corpus_facade.py`
- `tests/test_core_facade/test_query.py`
- `tests/perf/bench_core_query.py`
- `docs/rust_backend.md`
- `sdd/research/202604/rust_core_next_candidates.md` only if the recommendation status is updated
- Handoff: `plans/202604/query_corpus_phase7_cleanup_handoff.md`

Work:

1. If Phase 6 authorizes deletion, remove `_evaluate_query_many_python` and make the public batch surface use the
   persistent Rust corpus path where a corpus is supplied.
2. Decide the compatibility behavior for `evaluate_query_many(query, changespecs)` without an explicit corpus:
   - either compile a temporary Rust corpus and document it as compatibility-only, or
   - keep a deprecated wrapper that forces callers toward `compile_query_corpus`.
3. Remove or rename legacy benchmark rows so future readers do not confuse the old one-shot regression with the shipped
   product path.
4. Update docs to say `evaluate_query_many` is no longer intentionally unported and explain the corpus invalidation
   contract.
5. Run full verification.

Exit criteria:

- `just rust-check` passes.
- `just check` passes.
- `just phase7-perf-check` passes.
- Docs and handoff agree on whether any Python batch compatibility shim remains.

## Cross-Phase Rules

- Do not route the TUI to Rust until Phase 4 shows the persistent path clears the gate.
- Do not delete `_evaluate_query_many_python` until Phase 6 explicitly authorizes deletion.
- Preserve substring semantics; do not introduce regex matching for user queries.
- Keep `ancestor:` behavior cycle-safe and query-specific.
- Treat `../sase-core` as a sibling repo: run Rust checks there through `just rust-check` from the sase repo, and note
  any sibling-repo changes in handoffs.
- If a phase changes files in `sase_100`, run `just check` before finishing. If it changes `../sase-core`, run
  `just rust-check` before finishing.
