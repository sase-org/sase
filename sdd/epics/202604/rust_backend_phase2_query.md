---
create_time: 2026-04-29 02:51:00
status: done
bead_id: sase-17
prompt: sdd/prompts/202604/rust_backend_phase2_query.md
---
# Rust Backend Migration Phase 2 Query Plan

## Context

`sdd/research/202604/rust_backend_migration.md` defines Phase 2 as the Rust port of the query tokenizer and evaluator. Phase
0 and Phase 1 have already established the relevant boundaries:

- `sase_101/src/sase/core/query_facade.py` routes query parsing, context construction, and per-row evaluation through
  `sase.core.backend.dispatch`.
- Existing Python query behavior lives in `src/sase/ace/query/{tokenizer.py,parser.py,evaluator.py,highlighting.py}`.
- `QueryEvaluationContext` already removes the old O(N^2) behavior by caching name/status maps, searchable text, and
  ancestor results across rows.
- `../sase-core` exists as the external Rust repo from Phase 1. It has `crates/sase_core` and `crates/sase_core_py`,
  plus the optional `sase_core_rs.parse_project_bytes(path, data) -> list[dict]` binding.
- `sase_101` has optional Rust targets in the `Justfile`: `just rust-install`, `just rust-test`, `just rust-clippy`,
  `just rust-check`, and `just bench-core`.

Phase 2 should not call Rust once per TUI row. The target shape is a compiled/batch API:

```text
compile_query(query: str) -> QueryProgramWire
evaluate_query_many(program, specs_wire) -> list[bool]
```

Per-row Python compatibility wrappers can exist, but the measurable path must evaluate a whole ChangeSpec list in one
FFI call.

## Agent Phase Split

### Phase 2A: Query Contract, Corpus, and Baseline Measurement

Goal: make query behavior explicit enough that a Rust implementation can be checked without rediscovering Python
semantics.

Scope in `sase_101`:

- Add query wire records in `src/sase/core/wire.py` or a focused sibling module:
  - `QueryTokenWire` with token kind, value, position, case sensitivity, and property key.
  - `QueryExprWire` or a JSON-safe tagged AST shape for `StringMatch`, `PropertyMatch`, `Not`, `And`, and `Or`.
  - `QueryProgramWire` for a compiled query handle's serializable representation. Keep this plain-data for parity tests;
    the PyO3 binding can use an opaque handle later if needed.
  - `QueryErrorWire` with kind, message, and position.
- Add conversion helpers between the current Python AST dataclasses and the wire AST.
- Expand `tests/test_core_golden.py` or add `tests/test_core_query_golden.py` with a query corpus covering:
  - quoted strings, case-sensitive strings, escapes, bare words, implicit and explicit `AND`, `OR`, `NOT`, and parens.
  - property filters: `status`, `project`, `ancestor`, `name`, and `sibling`.
  - shorthand forms: `!`, `!!`, `!!!`, `@`, `!@`, `@@@`, `$`, `!$`, `$$$`, `*`, `%d/%m/%r/%s/%w/%y`, `+`, `^`, `~`, and
    `&`.
  - malformed queries and exact Python error messages/positions where those messages are user-visible.
- Add a query benchmark harness, likely `tests/perf/bench_core_query.py`, that reports:
  - Python direct parse only.
  - Python facade parse only.
  - Python `parse_query + build_query_context + evaluate_query_with_context` over 100, 1k, and 10k specs.
  - Later Rust direct and Rust facade numbers when the binding exists.
- Inventory regex semantics explicitly. Current query matching is substring-based with two Python `re` helpers for
  status suffix stripping, not user-supplied regex matching. Capture that as a short doc comment/test note so Phase 2B
  does not overbuild a regex engine or accidentally introduce regex query semantics.

Exit criteria:

- Golden tests pin token stream, AST/canonical form, evaluation matrix, and selected error messages.
- Benchmark output establishes the optimized Python baseline after `QueryEvaluationContext`.
- `pytest -k "core_query or core_golden or query"` passes.

### Phase 2B: Pure-Rust Query Tokenizer and Parser

Goal: implement the Python query grammar in `../sase-core` without touching Python dispatch yet.

Scope in `../sase-core`:

- Add `crates/sase_core/src/query/` with `tokenizer.rs`, `parser.rs`, `types.rs`, and `mod.rs`.
- Mirror the Python token rules from `src/sase/ace/query/tokenizer.py`, including the current quirks:
  - standalone `!`, `@`, and `$` transform to special searches only at end-of-input or before whitespace.
  - `!!`, `!@`, and `!$` are only special when standalone.
  - `*` means "any special" in the tokenizer/highlighter even though the grammar comment still mentions `!@$`.
  - `%y` maps to `READY`; ensure highlighter/tests do not omit it.
  - property values can be bare words or quoted strings with the same escape behavior as quoted search strings.
- Mirror parser precedence and AST folding:
  - `NOT` binds tightest.
  - implicit `AND` is supported.
  - `OR` binds loosest.
  - `!!`, `!@`, and `!$` expand to `Not(...)`.
  - `*` expands to `Or(!!!, @@@, $$$)`.
- Add Rust unit tests from the Phase 2A corpus.
- Export pure functions from `sase_core`:
  - `tokenize_query(query: &str) -> Result<Vec<QueryTokenWire>, QueryErrorWire>`
  - `parse_query(query: &str) -> Result<QueryExprWire, QueryErrorWire>`
  - `canonicalize_query(expr: &QueryExprWire) -> String`

Exit criteria:

- Rust tokenizer/parser tests pass without Python.
- Rust canonical strings match Python for the golden corpus.
- No PyO3 dependency leaks into the pure `sase_core` crate.

### Phase 2C: Pure-Rust Evaluation Engine and Batch API

Goal: evaluate compiled queries against `ChangeSpecWire` lists in Rust with the same semantics as Python.

Scope in `../sase-core`:

- Add Rust equivalents for Python evaluator helpers:
  - searchable text extraction from `ChangeSpecWire`.
  - base status stripping for workspace suffixes and legacy `READY TO MAIL`.
  - error suffix detection for commits, hooks, comments, mentors, and status-derived suffixes.
  - running-agent and running-process marker checks.
  - `status`, `project`, `name`, `sibling`, and recursive `ancestor` property matching.
- Add a Rust `QueryEvaluationContext` equivalent built once per list:
  - name map.
  - status map.
  - searchable text/lowercase cache.
  - ancestor memo.
- Add batch-oriented pure APIs:
  - `compile_query(query: &str) -> Result<QueryProgram, QueryErrorWire>`.
  - `evaluate_query_many(program: &QueryProgram, specs: &[ChangeSpecWire]) -> Vec<bool>`.
  - Optional internal `evaluate_query_one` for tests only.
- Keep path/name handling aligned with Python:
  - project name comes from `ChangeSpecWire.project_basename`.
  - sibling matching uses the same reverted suffix stripping as `sase.core.changespec.strip_reverted_suffix`.
  - string matching is substring matching, case-insensitive via lowercasing, not regex.
- Add Rust parity tests using fixtures exported from the Python golden corpus. Normalize Phase 1's known
  `source_span.end_line` difference if it appears in shared snapshots.

Exit criteria:

- `cargo test --workspace` passes in `../sase-core`.
- Rust evaluation results match Python's golden matrix.
- Batch evaluation is the primary public API in the Rust crate.

### Phase 2D: PyO3 Binding and Python Facade Integration

Goal: expose the Rust query engine through `sase_core_rs` and route Python query calls through it only when requested.

Scope in `../sase-core`:

- Extend `crates/sase_core_py/src/lib.rs` with plain-data PyO3 functions:
  - `tokenize_query(query: str) -> list[dict]`.
  - `parse_query(query: str) -> dict`.
  - `canonicalize_query(expr: dict) -> str` if useful for parity tests.
  - `evaluate_query_many(query: str | dict, specs: list[dict]) -> list[bool]`.
- Start with one-shot `evaluate_query_many(query, specs)` that compiles and evaluates in one call. Add an opaque
  compiled-program handle only if benchmarks show compilation is material.
- Convert Rust `QueryErrorWire` into `ValueError` or a more specific Python exception whose message matches Python
  enough for existing UI validation.

Scope in `sase_101`:

- Add Python adapters from `ChangeSpec` to `ChangeSpecWire` dicts for query evaluation. Reuse `changespec_to_wire()` and
  `to_json_dict()` rather than reaching into `ChangeSpec` manually at every call site.
- Extend `src/sase/core/query_facade.py` to register Rust implementations only when `sase_core_rs` exposes the query
  functions.
- Preserve existing public APIs:
  - `parse_query(query) -> QueryExpr` should still return the Python AST shape, even when Rust is selected.
  - `evaluate_query(query, cs, all_changespecs)` and `evaluate_query_with_context(query, cs, ctx)` should keep their
    signatures for compatibility.
- Add a new batch facade API for the TUI and CLI hot paths:
  - `evaluate_query_many(query, changespecs) -> list[bool]`.
  - Optionally `compile_query(query)` and `evaluate_compiled_query_many(program, changespecs)` if the Rust/Python
    contract needs a stable compiled representation.
- Dual-run should compare Python batch results to Rust batch results and return Python results when
  `SASE_CORE_DUAL_RUN=1`.

Exit criteria:

- `SASE_CORE_BACKEND=rust` exercises query parser/evaluator bindings when the extension is installed.
- Missing Rust extension still leaves pure-Python installs working.
- Existing tests that monkeypatch old query functions keep passing.

### Phase 2E: Move Hot Call Sites to Batch Query Evaluation

Goal: make phase 2 measurable in user-facing paths by avoiding per-row FFI dispatch.

Scope in `sase_101`:

- Update high-volume query filtering call sites to use the batch facade:
  - `src/sase/ace/tui/actions/changespec/_loading.py`.
  - `src/sase/axe/cli.py`.
  - `src/sase/main/search_handler.py`.
  - `src/sase/axe/check_cycles.py` if it can use the same batch shape without weakening behavior.
- Keep low-volume or compatibility paths on the old per-row functions unless they are trivial to route through the batch
  helper.
- Add tests that prove batch results match the old `evaluate_query_with_context` path for representative lists,
  including ancestor and sibling filters.
- Keep syntax highlighting in Python for this phase unless benchmarks or product needs justify a separate Rust display
  tokenizer. If touched, treat highlighting spans as a separate contract because display tokens are not identical to
  parser tokens.

Exit criteria:

- TUI and CLI filtering use one batch query call per list refresh/search, not one backend dispatch per row.
- Existing query behavior stays unchanged under `SASE_CORE_BACKEND=python`.
- Dual-run logs query mismatches with operation names such as `evaluate_query_many`.

### Phase 2F: Verification, Benchmarks, and Rollout Decision

Goal: decide whether the Rust query backend should remain opt-in, become the default for query operations, or be skipped
for now because Python is already fast enough.

Scope:

- Run Python-side checks in `sase_101`:
  - `just install` if the workspace has not been installed recently.
  - focused query/core tests.
  - `just rust-install` to install the updated extension.
  - `just bench-core` for parser regression awareness.
  - the new `just bench-query` target if Phase 2A adds one.
  - `just check` before handoff because this repo changed.
- Run Rust-side checks in `../sase-core`:
  - `cargo fmt --all -- --check`.
  - `cargo clippy --workspace --all-targets -- -D warnings`.
  - `cargo test --workspace`.
- Measure at least these query scenarios:
  - parse only.
  - parse + evaluate 100 specs.
  - parse + evaluate 1k specs.
  - parse + evaluate 10k specs.
  - dual-run overhead.
- Apply the research go gate: Rust should be at least 2x faster for large lists after FFI/conversion cost before
  considering a default flip.
- Document the result in the plan handoff or a short research update. If Rust does not clear the gate, keep the backend
  optional and leave the batch Python path as the useful product improvement.

Exit criteria:

- All modified repos pass their required checks, or failures are documented with concrete causes.
- The final handoff states whether phase 3 should proceed immediately or whether profiling says a different bottleneck
  should be attacked first.

## Cross-Agent Dependency Order

1. Phase 2A must land first; it defines the contract and benchmark target.
2. Phase 2B and Phase 2C can be separate agents after 2A, but 2C should not finalize public APIs until 2B's AST shape is
   stable.
3. Phase 2D depends on 2B and 2C.
4. Phase 2E depends on 2D and should be kept in `sase_101` only.
5. Phase 2F lands last and should not be combined with feature work.

## Non-Goals

- Do not remove the Python query implementation.
- Do not flip `SASE_CORE_BACKEND` default to `rust` during phase 2 implementation.
- Do not introduce user-facing regex query syntax. The current language is substring/property matching.
- Do not port plugin, VCS, workspace, or Textual UI behavior.
- Do not make the Rust extension a required dependency of `sase`.
