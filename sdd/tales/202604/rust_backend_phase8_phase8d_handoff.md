# Phase 8D Handoff: Direct-Rust Ported Facades And Delete Clear-Win Python Halves

Bead: `sase-1f.4`. Plan: `plans/202604/rust_backend_phase8.md`. Phase 8D rewires the three high-confidence Rust wins —
`parse_project_bytes`, `parse_query`, and `scan_agent_artifacts` — from `dispatch(...)`-with-Python-fallback to direct
calls through `sase.core.rust.require_rust_binding(...)`. The corresponding Python fallback closures and walker helpers
that existed only to back the legacy dispatcher Python branch are deleted.

`evaluate_query_many` is *not* touched here: Phase 8B took the deferred/unported exit
(`plans/202604/rust_backend_phase8_phase8b_handoff.md`), so `_evaluate_query_many_python` stays as the authoritative
implementation and the facade keeps dispatching through it with `rust_unavailable="python"` until Phase 8C tears down
the dispatcher wrapper. Phase 8D follows the Phase 8B handoff's explicit instruction: "Phase 8D should remove only the
dispatcher wrapping for this surface, mirroring the rewire it does for `build_query_context` and friends" — and even
that wrapping is left for Phase 8C (Phase 8C's scope per the plan), since Phase 8D should not preempt the unported
facade rewire.

## What landed

### Direct-Rust facade rewires

- `src/sase/core/parser_facade.py` — `parse_project_bytes` now calls
  `require_rust_binding("parse_project_bytes")` directly and rehydrates the dict result via
  `changespec_wire_from_dict`. The `_python_impl` tempfile-bridge closure and the `_rust_parse_project_bytes_impl`
  adapter are deleted; the only remaining import is the strict loader from `sase.core.rust`. `parse_project_file`
  remains an intentionally Python-only host-logic API (file-path entry point — the Rust binding consumes bytes; routing
  it through Rust would either re-read the file or duplicate work).
- `src/sase/core/query_facade.py` — `parse_query` now calls `require_rust_binding("parse_query")` directly, builds the
  wire dict via `query_expr_wire_from_dict`, and projects to the Python `QueryExpr` AST via `query_expr_from_wire`. The
  `_rust_parse_query_impl` adapter and the `parse_query_python` routing path through this facade are deleted. The
  module-level `parse_query_python` import stays because `_evaluate_query_many_python` (the deferred batch path)
  consumes it. `build_query_context` / `evaluate_query` / `evaluate_query_with_context` / `evaluate_query_many` keep
  their `dispatch(..., rust_unavailable="python")` wrappers — they are 8C / 8B-deferred surfaces, out of scope for 8D.
- `src/sase/core/agent_scan_facade.py` — `scan_agent_artifacts` now calls
  `require_rust_binding("scan_agent_artifacts")` directly with the wire-shaped options dict and rehydrates the result
  via `agent_scan_wire_from_dict`. The Python walker (`scan_agent_artifacts_python`, `_scan_artifact_dir`,
  `_load_marker_json`, `_marker_exists`, `_safe_iterdir`, `_supported_workflow_dir`, the eight `_coerce_*` /
  `_*_marker_from_dict` helpers, `_workflow_state_from_dict`, `_workflow_step_from_dict`, `_prompt_step_from_dict`,
  `_plan_path_from_dict`, `_read_raw_prompt_snippet`, the `_RAW_PROMPT_FILE` constant, and the unused
  `WORKFLOW_STATE_DIR_*` / `DONE_WORKFLOW_DIR_*` re-imports) is deleted. `with_options` and `_options_to_dict`
  survive: `with_options` is a public convenience used by callers, `_options_to_dict` is the Rust-side dict adapter.
  The facade now re-exports the agent-scan wire dataclasses (`AgentArtifactRecordWire`, `AgentMetaWire`,
  `DoneMarkerWire`, etc.) so the public schema stays reachable from the facade entry point even though the marker
  wires are no longer constructed in this module.

### Strict loader pragma cleanup

- `src/sase/core/rust.py` — dropped the `# pyvision: tests/test_core_rust.py` pragma on `require_rust_binding`. Phase
  8D adds three product call sites (parser, query, agent-scan facades), so pyvision now sees the symbol used inside
  `src/`.

### Test rewiring

- `tests/test_core_facade/test_parser.py` — replaced the four dispatcher-era tests
  (`test_parse_project_file_rust_backend_still_uses_python_parser`,
  `test_parse_project_bytes_rust_unavailable_keeps_python`,
  `test_parse_project_bytes_rust_backend_uses_rust_impl`,
  `test_parse_project_bytes_rust_backend_missing_binding_raises_cleanly`,
  `test_parse_project_bytes_dual_run_logs_comparison`) with the new direct-Rust contract:
  - `test_parse_project_bytes_uses_rust_binding`: fake `sase_core_rs` binding records arguments, returns parity
    output, exercises the dict→`ChangeSpecWire` rehydration code path the facade owns.
  - `test_parse_project_bytes_missing_extension_raises_importerror`: missing wheel surfaces as `ImportError` whose
    message names the package.
  - `test_parse_project_bytes_stale_wheel_raises_attributeerror`: present wheel without the binding surfaces as
    `AttributeError` whose message names the operation.
  - `test_parse_project_bytes_rust_error_surfaces` (kept, now without the dispatcher / env-var setup): Rust-side
    `ValueError` propagates verbatim.
- `tests/test_core_facade/test_query.py` — same shape:
  `test_parse_query_uses_rust_binding`, `test_parse_query_missing_extension_raises_importerror`,
  `test_parse_query_stale_wheel_raises_attributeerror`. The remaining tests (`test_query_parse_and_evaluate_match_python`,
  `test_evaluate_query_many_*`, `test_unported_query_facade_apis_*`) keep their existing shape — they test the
  unported facade APIs and the Phase 8B deferral, which Phase 8D explicitly does not touch.
- `tests/test_core_agent_scan.py` — removed the autouse `_clean_backend_env` fixture (no env-var behavior remains for
  this surface), removed `test_python_facade_and_dispatch_agree`, and replaced the four
  Rust-dispatch / dual-run tests
  (`test_scan_agent_artifacts_rust_unavailable_keeps_python`,
  `test_scan_agent_artifacts_rust_without_impl_raises`,
  `test_scan_agent_artifacts_rust_backend_uses_rust_impl`,
  `test_scan_agent_artifacts_dual_run_logs_comparison`,
  `test_scan_agent_artifacts_dual_run_records_mismatch`,
  `test_rust_extension_parity`) with the new direct-Rust contract:
  `test_scan_agent_artifacts_calls_rust_binding`,
  `test_scan_agent_artifacts_missing_extension_raises_importerror`,
  `test_scan_agent_artifacts_stale_wheel_raises_attributeerror`. The 25 pre-existing fixture / golden / soft-error
  / option-handling tests are unchanged and now exercise the Rust binding through the facade transparently (the real
  `sase_core_rs` extension is installed in this workspace; the fake-binding path is covered by the three new
  contract tests above).
- `tests/test_core_facade/test_backend_contract.py` — removed `parse_project_bytes`, `parse_query`, and
  `scan_agent_artifacts` from `SHIPPED_OPERATIONS`. They no longer go through `dispatch(...)`; the per-facade tests
  named above pin their direct-Rust contract instead. The
  `test_facade_inventory_matches_expected_classification` walker is unchanged and validates the new (smaller)
  shipped set against the live facade source.
- `tests/test_query_parser.py` — three tests (`test_parse_error_empty_query`, `test_parse_error_unmatched_paren`,
  `test_parse_error_missing_operand`) were pinned to `SASE_CORE_BACKEND=python` to assert Python-parser-specific
  `QueryParseError` text. After Phase 8D the public `sase.ace.query.parse_query` always reaches the Rust binding,
  which raises a plain `ValueError` with a different shape. The tests now call `parse_query_python` directly — the
  Python parser's error contract is what they actually pin, not the public `parse_query` routing.
- `tests/test_core_facade/_helpers.py` — switched the `RUST_EXTENSION_MODULE_NAME` import from `sase.core.backend` to
  `sase.core.rust` so the helpers stay alive when 8F deletes the legacy backend module.
- `tests/test_agent_model_timestamps.py` — switched from `scan_agent_artifacts_python` (deleted) to
  `scan_agent_artifacts` (the facade, now direct-Rust).

### Bench-harness adjustment

- `tests/perf/bench_agent_scan.py` — dropped the four scenarios that depended on the deleted Python walker
  (`scan_python_facade`, `scan_python_facade_no_prompt_steps`, plus the Python-walker calls inside
  `s_running_from_shared_snapshot` / `s_all_from_shared_snapshot` were repointed to `scan_agent_artifacts`
  itself). Updated the smoke test (`test_bench_agent_scan_smoke`) to assert on `scan_rust_facade` instead of
  `scan_python_facade`. Phase 8F owns the larger bench rework that drops the remaining `BACKEND_ENV_VAR` /
  `is_rust_available` references; the changes here are the minimum needed to keep `just bench-agent-scan` and
  `pytest -m slow tests/perf/bench_agent_scan.py` import-healthy after the walker deletion.
- Other perf benches (`tests/perf/bench_core_parse.py`, `tests/perf/bench_core_query.py`,
  `tests/perf/bench_status_state_machine.py`, `tests/perf/bench_workflow_complete.py`) still import
  `BACKEND_ENV_VAR` / `is_rust_available` / `load_rust_extension` from `sase.core.backend`. Those legacy helpers
  still exist (Phase 8F will delete them); the benches keep working, although their `python_facade` /
  `rust_facade` scenarios for `parse_project_bytes` and `parse_query` now produce identical numbers since both
  paths run the Rust binding. Phase 8F should retitle / dedupe those scenarios as part of its bench rework.

### Parity-gate adjustment

- `tests/parity/dual_run_parity.py` — removed `parse_project_bytes`, `parse_query`, and `scan_agent_artifacts` from
  the gate's `SHIPPED_OPERATIONS`. They no longer produce dual-run records (no dispatcher, no `rust_impl`
  registration), so the gate would otherwise fail with "shipped op X produced no dual-run record". The
  `_exercise_parser` / `_exercise_query` / `_exercise_agent_scan` helpers are kept and still call the facades —
  they no longer contribute records but they verify the ported surfaces stay import-healthy under
  `SASE_CORE_DUAL_RUN=1`. `DOCUMENTED_DIVERGENCE` is now the empty set (the only entry was
  `parse_project_bytes`, whose `source_span.end_line` parity is now pinned by the golden contract in
  `tests/test_core_parity_smoke.py`). The module docstring records the Phase 8D scope change.

## Updated Phase 8 operation disposition

Supersedes the Phase 8A and 8B handoffs for the rows it touches.

### Direct Rust now (Phase 8D landed)

| Operation              | Facade                                  | Notes                                                                                       |
| ---------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------- |
| `parse_project_bytes`  | `src/sase/core/parser_facade.py`        | Direct Rust via `require_rust_binding`; Python tempfile-bridge fallback deleted.            |
| `parse_query`          | `src/sase/core/query_facade.py`         | Direct Rust via `require_rust_binding`; Python `parse_query_python` routing through facade deleted (still importable from `sase.ace.query.parser`). |
| `scan_agent_artifacts` | `src/sase/core/agent_scan_facade.py`    | Direct Rust via `require_rust_binding`; `scan_agent_artifacts_python` and walker helpers deleted; wire types re-exported from the facade. |

### Direct Rust now (Phase 8E targets, unchanged)

| Operation                       | Facade                                  | Notes                                                                                       |
| ------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------- |
| `read_status_from_lines`        | `src/sase/core/status_facade.py`        | Still dispatched.                                                                           |
| `apply_status_update`           | `src/sase/core/status_facade.py`        | Still dispatched.                                                                           |
| `plan_status_transition`        | `src/sase/core/status_facade.py`        | Still dispatched.                                                                           |
| `parse_git_name_status_z`       | `src/sase/core/git_query_facade.py`     | Still dispatched.                                                                           |
| `parse_git_branch_name`         | `src/sase/core/git_query_facade.py`     | Still dispatched.                                                                           |
| `derive_git_workspace_name`     | `src/sase/core/git_query_facade.py`     | Still dispatched.                                                                           |
| `parse_git_conflicted_files`    | `src/sase/core/git_query_facade.py`     | Still dispatched.                                                                           |
| `parse_git_local_changes`       | `src/sase/core/git_query_facade.py`     | Still dispatched.                                                                           |

### Direct Python because intentionally unported (Phase 8C target list, unchanged from 8B)

| Operation                       | Facade                                  | Direct Python target                          |
| ------------------------------- | --------------------------------------- | --------------------------------------------- |
| `build_query_context`           | `src/sase/core/query_facade.py`         | `build_query_context_python`                  |
| `evaluate_query`                | `src/sase/core/query_facade.py`         | `evaluate_query_python`                       |
| `evaluate_query_with_context`   | `src/sase/core/query_facade.py`         | `evaluate_query_with_context_python`          |
| `evaluate_query_many` (8B)      | `src/sase/core/query_facade.py`         | `_evaluate_query_many_python`                 |
| `build_changespec_graph_index`  | `src/sase/core/graph_index_facade.py`   | `build_changespec_graph_index_python`         |
| `transition_changespec_status`  | `src/sase/core/status_facade.py`        | `transition_changespec_status_python`        |

## Verification

```
just install
.venv/bin/python -m pytest tests/test_core_facade/test_parser.py \
    tests/test_core_facade/test_query.py \
    tests/test_core_facade/test_backend_contract.py \
    tests/test_core_agent_scan.py \
    tests/test_agent_model_timestamps.py
.venv/bin/python -m pytest tests/test_core_golden.py \
    tests/test_core_dual_run.py tests/test_core_backend.py \
    tests/test_core_health.py tests/test_core_parity_smoke.py \
    tests/test_core_rust.py
just parity-check
just check
```

All commands ran clean. `just check` exit 0 covers `fmt`, `lint` (keep-sorted, ruff, mypy, pyscripts, pyvision), and
the full `test` target (6521 passed, 6 skipped, 0 failed).

`just phase7-perf-check` was not re-run; its known status-helper noise floor is Phase 8E / 8F territory and Phase 8D
did not touch the status or git facades.

## Hand-off notes for Phase 8C

- **Unported query / graph / status facades**: These still call `dispatch(..., rust_unavailable="python", ...)`. Phase
  8C should switch each one to a direct call into its `*_python` implementation and drop the dispatcher branch.
  `evaluate_query_many` is in the same bucket as `build_query_context` / `evaluate_query` / `evaluate_query_with_context`
  / `build_changespec_graph_index` / `transition_changespec_status` — five rewires plus the deferred `evaluate_query_many`
  one for a total of six.
- **Health rewrite**: `src/sase/core/health.py` still imports `Backend, get_active_backend, is_dual_run_enabled,
  load_rust_extension`. Phase 8C is the place to collapse it to `require_rust_extension` plus a cheap
  `require_rust_binding("parse_query")` probe and to drop the `backend` / `dual_run` / `rust_required` fields from
  `BackendHealthReport`. Phase 8A intentionally left this for 8C.
- **TUI backend indicator**: `src/sase/ace/tui/widgets/backend_indicator.py` still reads
  `get_active_backend` / `is_dual_run_enabled`. 8C decides whether to delete the indicator outright or replace it
  with a "Rust core installed" health pin.

## Hand-off notes for Phase 8E

- **Status / Git facades unchanged**: Phase 8D did not touch
  `src/sase/core/status_facade.py` or `src/sase/core/git_query_facade.py`. The strict loader (`require_rust_binding`)
  is the supported path; the Phase 8D facades above are the working precedent for the wiring shape and for the
  ImportError / AttributeError contract tests.
- **Status-helper noise floor**: Phase 8B's verification noted `apply_status_update` runs at the sub-50µs scale where
  measurement noise dominates. Phase 8E owns the re-measurement and the decision about whether to keep
  `read_status_from_lines_python` / `apply_status_update_python` / `plan_status_transition_python` as host logic.
  Nothing in this handoff changes that calculus.

## Hand-off notes for Phase 8F

- **Bench harnesses still import legacy backend symbols**: `tests/perf/bench_core_parse.py`,
  `tests/perf/bench_core_query.py`, `tests/perf/bench_agent_scan.py`,
  `tests/perf/bench_status_state_machine.py`, and `tests/perf/bench_workflow_complete.py` still import
  `BACKEND_ENV_VAR` / `is_rust_available` / `load_rust_extension` from `sase.core.backend`. Phase 8F's bench rewrite
  must either drop those imports or convert each scenario to a strict-loader / facade call. Phase 8D made the minimum
  changes to `bench_agent_scan.py` to keep it import-healthy after the walker deletion; the larger bench cleanup is
  Phase 8F.
- **Parity gate now smaller**: `tests/parity/dual_run_parity.py` still asserts every dispatched-shipped op produces a
  dual-run record. After 8D the list is the eight status / Git ops in the table above. Phase 8F deletes the gate
  entirely (per the plan); the trailing `_exercise_parser` / `_exercise_query` / `_exercise_agent_scan` helpers can
  be deleted with it without further unwinding (their facade calls now run the Rust path directly and the
  contracts are pinned by per-facade tests).
- **`rg` sweep**: `rg "load_rust_extension|is_rust_available|sase\\.core\\.backend"` in `src/sase/core/` still hits
  `health.py` and `__init__.py`. Phase 8C handles `health.py`; Phase 8F handles `__init__.py` together with the
  whole-module deletion of `sase/core/backend.py`.

## Hand-off notes for Phase 8G

- **Docs**: `docs/rust_backend.md` still describes the dispatched ported operations. Phase 8G should update the
  ported-surfaces section to call out the direct-Rust path through `sase.core.rust` for `parse_project_bytes`,
  `parse_query`, and `scan_agent_artifacts` (and add the rest after Phase 8E lands).
- **Golden contract**: The Phase 8 plan asks Phase 8G to "replace live Python/Rust parity language with golden-contract
  language". For the three Phase 8D surfaces:
  - parser: `tests/core_golden/` and `tests/test_core_parity_smoke.py` already pin the wire/JSON contract.
  - query parse: `tests/test_core_query_golden_*.py` already pin the AST contract.
  - agent scan: `tests/test_core_agent_scan.py` plus `tests/agent_scan_golden/` already pin the snapshot contract.
  No new golden fixtures were added in 8D; the existing ones now run against the Rust binding by default.
