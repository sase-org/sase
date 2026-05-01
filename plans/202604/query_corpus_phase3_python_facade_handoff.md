---
create_time: 2026-05-01 00:00:00 -0400
bead_id: sase-1o.3
status: complete
---
# Query Corpus Phase 3 Python Facade Handoff

## Changed

- Added `src/sase/core/query_corpus_facade.py` as the handle-oriented Python
  facade for the Phase 2 PyO3 bindings.
- Added the `QueryCorpus` wrapper dataclass with:
  - `source_list_id`: `id(changespecs)` for the source list object used to
    build the corpus;
  - `expected_length`: the list length at compile time;
  - `rust_handle`: the owned `sase_core_rs.QueryCorpusHandle`.
- Added `compile_query_corpus(changespecs)`, which converts each `ChangeSpec`
  to a `ChangeSpecWire` JSON dict once, calls `sase_core_rs.compile_corpus`,
  and validates the returned handle length.
- Added `evaluate_query_many_with_corpus(query, corpus)`, which validates the
  wrapper, compiles the query through `sase_core_rs.compile_query`, and
  evaluates through `sase_core_rs.evaluate_many`.
- Kept `sase.core.query_facade.evaluate_query_many(query, changespecs)` on the
  existing Python batch path. No product/TUI routing changed in this phase.

## Tests

- Added fake-binding tests in `tests/test_core_facade/test_query.py` proving:
  - corpus compilation performs one conversion pass over the source list;
  - persistent-corpus evaluation calls `compile_query` and `evaluate_many`, not
    legacy `evaluate_query_many`;
  - a wrapper whose expected length no longer matches the Rust handle fails
    before query compilation or evaluation;
  - missing new bindings fail through `require_rust_binding` and name the
    missing operation.

Verified:

```bash
just install
.venv/bin/pytest tests/test_core_facade/test_query.py
```

## Invalidation Contract For Phase 5

- The TUI cache must associate a compiled `QueryCorpus` with the exact
  `_all_changespecs` list object it was built from.
- A cached corpus is reusable only when
  `cached_corpus.source_list_id == id(current_changespecs)` and
  `cached_corpus.expected_length == len(current_changespecs)`.
- When `_apply_changespecs()` or `_apply_reloaded_changespecs()` receives a
  different list object, Phase 5 must build a new corpus with
  `compile_query_corpus(current_changespecs)` before routing filter evaluation
  through `evaluate_query_many_with_corpus(...)`.
- `evaluate_query_many_with_corpus()` also asks the Rust handle for `len()` and
  refuses evaluation if it differs from `expected_length`. This catches a
  corrupted/stale wrapper before returning mismatched results, but it cannot
  know the live list identity by itself; the TUI must still perform the
  `source_list_id` check before using the cached corpus.

## Remaining Work

- Phase 4 must add benchmark rows for corpus compile cost, fully persistent
  evaluation, and the query-keystroke path.
- Phase 5 must wire the TUI product path only if Phase 4 authorizes the route.
