---
create_time: 2026-04-29 11:58:25
status: done
prompt: sdd/prompts/202604/rust_backend_unimplemented_fallbacks.md
---
# Plan: make unported Rust backend facade methods fall back to Python

## Problem

`SASE_CORE_BACKEND=rust` currently means "every dispatched facade call must have a registered Rust implementation." That
was useful early in the migration, but it now leaks migration internals into normal code paths:

- `parse_project_file()` was already fixed to stay Python-only because the Rust API is bytes-shaped.
- Other public facade methods are still dispatched with no Rust implementation: `build_query_context`, `evaluate_query`,
  `evaluate_query_with_context`, `build_changespec_graph_index`, `read_status_from_lines`, `apply_status_update`, and
  `transition_changespec_status`.
- Under `SASE_CORE_BACKEND=rust`, any caller that reaches one of those methods can raise `RustBackendUnavailableError`
  even though a correct Python implementation exists and the method has not actually been ported.

The desired behavior is hybrid and per-operation: use Rust for operations that have a shipped binding, and use Python
for operations that are intentionally unported. Unimplemented migration candidates should not break the TUI, CLI, or
tests just because the Rust backend is selected.

## Current Surface

Rust-backed operations that should remain strict because the binding is shipped and documented:

- `parse_project_bytes`
- `parse_query`
- `evaluate_query_many`
- `scan_agent_artifacts`

Unported facade operations that should fall back to Python under `SASE_CORE_BACKEND=rust`:

- Query context and per-row evaluation: `build_query_context`, `evaluate_query`, `evaluate_query_with_context`
- Graph index: `build_changespec_graph_index`
- Status helpers and transition wrapper: `read_status_from_lines`, `apply_status_update`, `transition_changespec_status`

`parse_project_file()` is already correct: it bypasses backend dispatch and calls `parse_project_file_python()`.

## Implementation Approach

1. Extend `sase.core.backend.dispatch` with an explicit per-call fallback policy. Keep the default strict to preserve
   existing guarantees for shipped Rust operations. Add a keyword such as `rust_unavailable="raise" | "python"` or
   `fallback_to_python_when_rust_missing=False`.

2. Mark intentionally unported facade methods as Python fallback operations. Update `query_facade.py`,
   `graph_index_facade.py`, and `status_facade.py` so those public APIs return the Python implementation when the active
   backend is Rust but no Rust impl is registered.

3. Keep shipped Rust operations strict, but make missing shipped bindings fail cleanly.
   - Register a Rust impl only when the extension is importable and exposes the expected attribute.
   - If `SASE_CORE_BACKEND=rust` is selected and a shipped operation's binding is missing, raise
     `RustBackendUnavailableError` with the operation name rather than surfacing a raw `AttributeError`.
   - Do not silently fall back for shipped Rust operations; otherwise a missing wheel or stale extension would make
     "rust mode" appear to work while not exercising Rust.

4. Preserve dual-run semantics.
   - If a Rust impl exists and `SASE_CORE_DUAL_RUN=1`, compare Python and Rust as today and return Python.
   - If an operation is marked Python-fallback and has no Rust impl, dual-run is a no-op, matching today's no-impl
     dual-run behavior.

5. Update tests.
   - Adjust `tests/test_core_backend.py` to cover the new fallback policy while retaining strict default behavior.
   - Replace tests that expect unported status/query facade methods to raise under `SASE_CORE_BACKEND=rust` with tests
     that assert they return Python results.
   - Add coverage for graph index and per-row query APIs under `SASE_CORE_BACKEND=rust`.
   - Add coverage that shipped operations still raise when their required Rust binding is unavailable, and that fake
     Rust bindings still get called when present.
   - Keep the existing `parse_project_file()` and snapshot-cache regression tests.

6. Update documentation and migration notes.
   - `docs/rust_backend.md`: document the hybrid backend policy: "rust" means Rust for shipped operations, Python for
     intentionally unported facade APIs. Keep the warning that shipped Rust operations require `sase_core_rs`.
   - `src/sase/core/__init__.py`: remove stale Phase 0 wording that says `SASE_CORE_BACKEND=rust` intentionally raises
     for Python-only operations.
   - `sdd/research/202604/rust_backend_migration.md`: update Phase 6 and Phase 8 if necessary. Phase 6 should no longer
     require an unsupported-operation test bucket for unported facades; instead, it should require this explicit
     per-operation fallback policy before any default flip. Phase 8 can keep the steady-state note that unported facades
     call Python directly.

## Validation

Run the repo-required install first because this is an ephemeral `sase_<N>` workspace:

```bash
just install
```

Focused validation:

```bash
just test tests/test_core_backend.py tests/test_core_facade.py tests/ace/changespec/test_snapshot_cache.py
```

Rust-backend reproduction coverage:

```bash
SASE_CORE_BACKEND=rust .venv/bin/python - <<'PY'
from pathlib import Path
from sase.core import query_facade, graph_index_facade, status_facade
from sase.core import parser_facade

path = Path("tests/core_golden/myproj.gp")
specs = parser_facade.parse_project_file(str(path))
expr = query_facade.parse_query('"alpha"')
ctx = query_facade.build_query_context(specs)
query_facade.evaluate_query_with_context(expr, specs[0], ctx)
graph_index_facade.build_changespec_graph_index(specs)
status_facade.read_status_from_lines(path.read_text().splitlines(True), specs[0].name)
PY
```

Full validation after file changes:

```bash
just check
```

If `../sase-core` is installed in the venv, also run the focused Rust parity tests that are not skipped locally:

```bash
just test tests/test_core_parity_smoke.py tests/test_core_agent_scan.py
```

## Non-goals

- Do not port status, graph-index, or per-row query evaluation to Rust in this change.
- Do not flip the default backend.
- Do not remove `RustBackendUnavailableError`; it is still useful for shipped Rust operations whose binding is missing
  or stale.
- Do not change public return types or wire records.
