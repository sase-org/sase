---
create_time: 2026-05-01 00:00:00 -0400
bead_id: sase-1o.5
status: complete
---
# Query Corpus Phase 5 TUI Routing Handoff

## Changed

- Added ChangeSpecs TUI state for the persistent query corpus cache:
  - `_query_corpus`
  - `_query_corpus_source_list_id`
- Routed the ChangeSpecs TUI filter path through
  `evaluate_query_many_with_corpus(self.query_string, cached_corpus)`.
- Added `_get_query_corpus_for_changespecs()` to compile or replace the corpus
  whenever the incoming ChangeSpec list object does not match the cached
  `source_list_id` and `expected_length`.
- Kept Phase 4's authorized default routing: the TUI does not fall back to the
  Python batch path when the persistent Rust bindings are missing or stale.
  Missing bindings fail through the strict corpus facade.
- Added focused TUI tests covering:
  - initial load corpus compilation;
  - per-query cache reuse without another ChangeSpec-to-wire conversion pass;
  - reload invalidation for a new list identity;
  - startup saved-query fallback against the already-loaded list;
  - hide-submitted / hide-reverted counts on the corpus route;
  - forced stale Rust handle detection before returning results.

## Invalidation Contract

The TUI cache is reusable only when all of these are true:

- `_query_corpus_source_list_id == id(changespecs)`
- `_query_corpus.source_list_id == id(changespecs)`
- `_query_corpus.expected_length == len(changespecs)`

If any check fails, the TUI recompiles the corpus for the current list before
filtering. `evaluate_query_many_with_corpus()` still validates the Rust handle
length, so a corrupted handle fails before producing mismatched filter results.

## Non-TUI Callers Still On `evaluate_query_many`

These callers still use the compatibility Python batch path and were not in
scope for Phase 5:

- `src/sase/axe/check_cycles.py`
- `src/sase/axe/cli.py`
- `src/sase/main/search_handler.py`

The legacy Rust one-shot binding remains only in the benchmark harness as a
diagnostic row.

## Verification

```bash
just install
.venv/bin/pytest tests/ace/tui/test_changespec_query_corpus_routing.py tests/test_core_facade/test_query.py -q
.venv/bin/pytest tests/test_ace_tui_app.py tests/ace/tui/test_reload_and_reposition.py tests/ace/tui/test_y_keymap_non_blocking.py -q
.venv/bin/python -m ruff check src/sase/ace/tui/actions/_state_init.py src/sase/ace/tui/actions/changespec/_loading.py tests/ace/tui/test_changespec_query_corpus_routing.py
just check
```
