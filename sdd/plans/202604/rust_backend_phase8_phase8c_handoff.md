# Phase 8C Handoff: Rewire Unported Facades And User Surfaces

Bead: `sase-1f.3`. Plan: `plans/202604/rust_backend_phase8.md`. Phase 8C makes deletion of `backend.dispatch` safe by
removing all Python-fallback uses from intentionally unported operations and turning the user-visible health/UI
surfaces into "Rust core installed" checks rather than backend selectors. The legacy `dispatch` and dual-run plumbing
remain in place — Phase 8D/8E rewire the ported facades and Phase 8F deletes the dispatcher.

## What landed

### Unported facades now call Python directly

The five operations classified as "intentionally unported" in the Phase 8A handoff no longer go through
`sase.core.backend.dispatch`. Each facade calls its `*_python` helper directly. They are no longer "fallbacks" — they
are host logic.

| Operation | Facade module | Direct call |
| --- | --- | --- |
| `build_query_context` | `src/sase/core/query_facade.py` | `build_query_context_python` |
| `evaluate_query` | `src/sase/core/query_facade.py` | `evaluate_query_python` |
| `evaluate_query_with_context` | `src/sase/core/query_facade.py` | `evaluate_query_with_context_python` |
| `build_changespec_graph_index` | `src/sase/core/graph_index_facade.py` | `build_changespec_graph_index_python` |
| `transition_changespec_status` | `src/sase/core/status_facade.py` | `transition_changespec_status_python` |
| `evaluate_query_many` | `src/sase/core/query_facade.py` | `_evaluate_query_many_python` |

(`evaluate_query_many` was reclassified as deferred/unported by Phase 8B — see
`plans/202604/rust_backend_phase8_phase8b_handoff.md`. Phase 8C drops the dispatcher seam for it along with the other
unported facades.)

Module docstrings were updated to describe the new contract: query parse / `evaluate_query_many` are still dispatched
(8B/8D own them); per-row eval / context build / graph index / side-effecting status transitions are Python-owned.

`graph_index_facade.py` no longer imports `dispatch` at all. `query_facade.py` and `status_facade.py` keep the dispatch
imports because their other entry points (`parse_query`, `evaluate_query_many`, status line helpers, planner) are still
shipped Rust operations routed via the dispatcher.

### Health surface no longer reports a selected backend

`src/sase/core/health.py` was rewritten to drop backend-selection state. The new contract:

- `BackendHealthReport` exposes only the rust-extension probe state (loaded? path/version? probe ok?). The fields
  `backend`, `dual_run`, and `rust_required` were removed.
- `check_backend_health()` calls `sase.core.rust.require_rust_extension()` (the Phase 8A strict loader) and treats a
  missing wheel as `status="error"`. There is no Python-mode escape hatch — `sase_core_rs` is a hard runtime
  dependency.
- Non-`ImportError` import-time failures still propagate verbatim so a misbuilt wheel surfaces clearly instead of
  looking like a missing install (matches the `is_rust_available()` invariant).

`src/sase/main/core_handler.py` was updated: the human-readable formatter no longer prints `backend:` or
`rust required:` lines.

`src/sase/main/parser_core.py` help strings now say "Inspect the required `sase_core_rs` Rust extension" instead of
"Inspect the sase.core backend".

### TUI backend indicator removed

The Phase 8 plan offered "remove the backend indicator entirely or replace it with a static core-health indicator only
if there is a product reason to keep visible status." After Phase 8C there is no runtime backend selection to
indicate, so the widget was removed entirely:

- Deleted `src/sase/ace/tui/widgets/backend_indicator.py` and `tests/test_backend_indicator.py`.
- Removed the `BackendIndicator` import + export from `src/sase/ace/tui/widgets/__init__.py`.
- Removed the import + `compose()` placement from `src/sase/ace/tui/app.py`.
- Removed the `#backend-indicator { ... }` rule from `src/sase/ace/tui/styles.tcss`.
- Deleted the now-unused `BackendDisplay` dataclass and `get_backend_display()` helper from
  `src/sase/core/backend.py` (their only consumers were the deleted indicator widget and its test). The associated
  `test_backend_display_*` cases in `tests/test_core_backend.py` were removed at the same time. The remaining
  `Backend` / `get_active_backend` / `is_dual_run_enabled` / `RustBackendUnavailableError` / `is_rust_available` symbols
  are kept (still used by `dispatch` and the contract tests) and pyvision pragmas point at `tests/test_core_backend.py`
  so the unused-public-symbol audit stays clean. Phase 8F deletes the rest with the dispatcher.

The neighboring `LLMOverrideIndicator`, `InactiveIndicator`, and `NotificationIndicator` widgets keep their slots in
the top bar — only the backend mode label is gone.

### Tests

- `tests/test_core_facade/test_graph_index.py` lost the `SASE_CORE_BACKEND=rust` "fallback" test (the facade no longer
  consults the env var). The pure happy-path test stays.
- `tests/test_core_facade/test_query.py`'s
  `test_unported_query_facade_apis_rust_without_impl_fall_back_to_python` was renamed to
  `test_unported_query_facade_apis_call_python_directly` — same assertions, but the docstring now states the Phase 8C
  contract: these helpers are Python-owned host logic regardless of any backend env var. The existing
  `parse_query` / `evaluate_query_many` Rust-routing tests are untouched.
- `tests/test_core_facade/test_backend_contract.py`'s `UNPORTED_OPERATIONS` tuple is now empty: the parametric
  "unported dispatch falls back to Python" test still runs (against zero ops, so it skips), and the
  `test_facade_inventory_matches_expected_classification` audit now succeeds because no facade declares an unported
  dispatch operation. The shipped-operations parametric path is unchanged.
- `tests/test_core_health.py` was rewritten to reflect the new report shape: tests no longer set
  `SASE_CORE_BACKEND` / `SASE_CORE_DUAL_RUN` and no longer assert on `backend`, `dual_run`, or `rust_required`.
  Coverage retained for: extension present probe ok, extension missing → error, misbuilt wheel surfaced verbatim,
  extension importable but missing `parse_query`, broken `parse_query` raises, JSON CLI ok/error, dataclass-frozen
  guard.
- All other tests that previously set `SASE_CORE_BACKEND=python|rust` (e.g. `test_core_backend.py`,
  `test_core_dual_run.py`, the perf benchmarks, `tests/parity/dual_run_parity.py`) were left untouched. Phase 8F owns
  their cleanup along with the dispatcher delete.

## Verification

```
just install
.venv/bin/python -m pytest tests/ --ignore=tests/perf --ignore=tests/parity -q
just check
```

`pytest` reports 6486 passed / 7 skipped / 1 deselected. `just check` is recorded below in this handoff.

## Hand-off notes for Phase 8D

- The dispatcher (`sase.core.backend.dispatch`) is still in use for: `parse_project_bytes`, `parse_query`,
  `evaluate_query_many`, `scan_agent_artifacts`, `read_status_from_lines`, `apply_status_update`,
  `plan_status_transition`, and the five `parse_git_*` / `derive_git_workspace_name` helpers. Phase 8D should rewire
  the parser / agent-scan / `parse_query` (and `evaluate_query_many` if Phase 8B succeeded) call sites to use the
  strict loader directly, then delete their Python halves per the Phase 8 plan.
- Phase 8B is still owed for `evaluate_query_many`. The "Temporarily blocked" row in the Phase 8A operation
  disposition is unchanged by 8C: the batch facade still uses `dispatch(..., rust_impl=...)`. If Phase 8B reclassifies
  it as deferred/unported, follow this handoff's pattern (call `_evaluate_query_many_python` directly from
  `query_facade.py`, drop `dispatch` for that entry point, update the contract test).
- The TUI top bar slot the indicator used is gone, not hidden. If a future product decision wants a "Rust core
  health" pip there, expose `check_backend_health()` to the TUI and add a green/red dot, but do not reintroduce a
  "backend mode" label.
- `BackendHealthReport` is intentionally narrower now. Any external caller that read `report.backend` /
  `report.dual_run` / `report.rust_required` will break. None were found in `src/` or `tests/`; the Phase 8A inventory
  did not flag any either.
