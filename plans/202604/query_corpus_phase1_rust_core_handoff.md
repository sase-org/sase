---
create_time: 2026-05-01 00:00:00
bead_id: sase-1o.1
status: complete
---
# Query Corpus Phase 1 Rust Core Handoff

## Changed

- Added `QueryCorpus` to the pure Rust `sase_core::query` evaluator API in the sibling `../sase-core` repo.
- `QueryCorpus` owns the `Vec<ChangeSpecWire>` and reusable derived data:
  lowercased names, parent lookup, base statuses, project directory names,
  sibling bases, searchable text, and lowercased searchable text.
- Added `evaluate_query_many_in_corpus(&QueryProgram, &QueryCorpus) -> Vec<bool>`.
- Kept the existing `evaluate_query_many(&QueryProgram, &[ChangeSpecWire])`
  API by constructing a temporary `QueryCorpus` and delegating to the new
  corpus evaluator.
- Kept ancestor memoization in `QueryEvaluationContext`, which is freshly
  allocated per evaluation call. It is not stored on `QueryCorpus`.
- Re-exported `QueryCorpus` and `evaluate_query_many_in_corpus` from
  `sase_core::query` and the crate root for Phase 2 PyO3 handles.

## Tests

- `cargo test -p sase_core --test query_evaluator_parity`
- `LD_LIBRARY_PATH=/home/bryan/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib PYO3_PYTHON=/home/bryan/projects/github/sase-org/sase_101/.venv/bin/python PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 cargo test --workspace` from `../sase-core`
- `LD_LIBRARY_PATH=/home/bryan/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib PYO3_PYTHON=/home/bryan/projects/github/sase-org/sase_101/.venv/bin/python PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 just check`

The focused parity suite covers the existing golden query matrix, ancestor
cycles, repeated evaluation against one corpus, and different queries against
the same corpus.

`just rust-check` was also attempted with the same PyO3 environment. It reached
clippy and failed on existing `notifications/store.rs` warnings unrelated to
this phase: two `clippy::incompatible_msrv` lock/unlock findings and one
`clippy::suspicious_open_options` finding.

## Notes For Phase 2

- The pure Rust handle is ready for PyO3 wrapping as an owned `QueryCorpus`.
- `evaluate_query_many` remains behavior-compatible for existing callers but
  still pays temporary corpus construction cost.
- The behavior-preserving refactor makes searchable text eager per corpus
  instead of lazy per query batch. This is intentional so the persistent handle
  pays that cost once when the corpus is compiled.
