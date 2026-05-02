---
create_time: 2026-04-30 23:01:25 -0400
bead_id: sase-1o.2
status: complete
---
# Query Corpus Phase 2 PyO3 Handoff

## Changed

- Added PyO3 handle classes in `../sase-core/crates/sase_core_py/src/lib.rs`:
  `QueryCorpusHandle` owns a pure-Rust `QueryCorpus`, and
  `QueryProgramHandle` owns a compiled `QueryProgram`.
- Exposed three new `sase_core_rs` bindings:
  `compile_corpus(specs)`, `compile_query(query)`, and
  `evaluate_many(program, corpus)`.
- Moved Python spec dict conversion into `compile_corpus` via the shared
  `ChangeSpecWire` conversion helper. Corpus construction runs after dict
  conversion and releases the GIL.
- `evaluate_many` releases the GIL while evaluating the compiled program
  against the persistent corpus.
- `compile_query` maps parser/tokenizer failures through the existing
  `query_error_to_pyerr` path, so Python receives `ValueError`.
- Kept the legacy `evaluate_query_many(query, specs)` binding for benchmark
  comparison and refactored it to reuse the same wire conversion helper.

## Tests

- `LD_LIBRARY_PATH=/home/bryan/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib PYO3_PYTHON=/home/bryan/projects/github/sase-org/sase_101/.venv/bin/python PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 cargo test -p sase_core_py query_ -- --nocapture`
- `LD_LIBRARY_PATH=/home/bryan/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib PYO3_PYTHON=/home/bryan/projects/github/sase-org/sase_101/.venv/bin/python PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 cargo test --workspace`

The PyO3 tests cover one corpus with multiple queries, one query with multiple
corpora, parity with the legacy one-shot binding, `ValueError` query compile
errors, and wrong handle type rejection messages that name the expected handle
class.

## Notes For Phase 3

- The Python facade can now treat `compile_corpus` as the only place where a
  list of `ChangeSpecWire` dicts crosses into Rust. Per-query evaluation should
  compile a `QueryProgramHandle` and call `evaluate_many`.
- `QueryCorpusHandle.__len__()` is available so the Phase 3 wrapper can compare
  expected corpus length before evaluation.
- The old `sase_core_rs.evaluate_query_many` binding still exists and should
  remain a diagnostic/benchmark row until the later cleanup phase decides
  whether to delete it.
