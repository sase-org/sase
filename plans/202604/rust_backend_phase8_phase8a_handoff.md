# Phase 8A Handoff: Inventory, Contract Freeze, And Direct Loader Foundation

Bead: `sase-1f.1`. Plan: `plans/202604/rust_backend_phase8.md`. Phase 8A is the foundation pass: it freezes the operation
disposition for Phase 8, lands a strict Rust loader that does not know about backend selection, and inventories every
`sase.core.backend` / `sase.core.dual_run` / `SASE_CORE_BACKEND` / `SASE_CORE_DUAL_RUN` reference so later subphases can
remove them mechanically. The legacy `dispatch` and dual-run plumbing is intentionally still in place; deletion is the
job of Phases 8C-8F.

## What landed

- `src/sase/core/rust.py` — new strict loader module exposing `require_rust_extension()` and
  `require_rust_binding(name)`. The helpers do not inspect environment variables and never silently return `None`. A
  missing wheel raises `ImportError` whose message names the package and `just install` / `just rust-install`. Other
  import-time failures (e.g. ABI mismatch) propagate verbatim, matching the existing `is_rust_available()` "broken
  wheel surfaces, missing wheel does not" split. `require_rust_binding(name)` delegates the import, then re-raises
  `AttributeError` with operation-specific text for stale wheels.
- `tests/test_core_rust.py` — six focused tests covering: returns the module on success; `ImportError` on missing
  wheel with installation hint; non-`ImportError` import failures propagate verbatim; binding lookup happy path;
  `AttributeError` mentioning the operation name for a stale wheel; binding lookup delegates the import-error path.
- `docs/rust_backend.md` — added a short "Phase 8 in progress" note at the top pointing at
  `plans/202604/rust_backend_phase8.md` and naming `src/sase/core/rust.py` as the post-Phase-8 loader. The body of the
  document still describes the Phase 6/7 dispatcher; Phase 8G will rewrite it for the steady state.
- `plans/202604/rust_backend_phase8_phase8a_handoff.md` — this file.

No code changes were made to existing facade modules, `src/sase/core/backend.py`, `src/sase/core/health.py`, the TUI
backend indicator, tests under `tests/test_core_facade/`, or the dual-run / parity machinery. The dispatcher remains the
only path through which Rust mode currently selects a binding.

## Phase 8 operation disposition

This is the contract Phase 8 will enforce. Each row names where the call site lives today and how Phase 8 will route it.

### Direct Rust now (Phase 8D / 8E targets)

These are the shipped Rust operations. They will move from
`dispatch(..., python_impl=..., rust_impl=...)` to `require_rust_binding(name)(...)` followed by typed wire conversion,
with the local Python fallback closure deleted unless a non-backend reason to keep it is documented in the relevant
subphase handoff.

| Operation | Facade | Phase | Notes |
| --- | --- | --- | --- |
| `parse_project_bytes` | `src/sase/core/parser_facade.py` | 8D | Python `_python_impl` is the temp-file bridge; deletion target. |
| `parse_query` | `src/sase/core/query_facade.py` | 8D | Python parser kept only if needed for unported per-row evaluation tests. |
| `scan_agent_artifacts` | `src/sase/core/agent_scan_facade.py` | 8D | `scan_agent_artifacts_python` and the marker-walking helpers are deletion targets. |
| `read_status_from_lines` | `src/sase/core/status_facade.py` | 8E | Python copy retained only if a non-test caller needs it after re-measurement. |
| `apply_status_update` | `src/sase/core/status_facade.py` | 8E | Same retention rule as `read_status_from_lines`. |
| `plan_status_transition` | `src/sase/core/status_facade.py` | 8E | Same retention rule. |
| `parse_git_name_status_z` | `src/sase/core/git_query_facade.py` | 8E | `*_python` deletion target after re-measurement. |
| `parse_git_branch_name` | `src/sase/core/git_query_facade.py` | 8E | Same. |
| `derive_git_workspace_name` | `src/sase/core/git_query_facade.py` | 8E | Same. |
| `parse_git_conflicted_files` | `src/sase/core/git_query_facade.py` | 8E | Same. |
| `parse_git_local_changes` | `src/sase/core/git_query_facade.py` | 8E | Same. |

### Direct Python because intentionally unported (Phase 8C)

These facades currently use `dispatch(..., rust_unavailable="python")`. Phase 8C will replace each with a direct call to
its `*_python` implementation and remove the dispatcher branch. The Python implementation continues to be the
authoritative one — these are not "fallback" any more, they are host logic.

| Operation | Facade | Direct Python target |
| --- | --- | --- |
| `build_query_context` | `src/sase/core/query_facade.py` | `build_query_context_python` |
| `evaluate_query` | `src/sase/core/query_facade.py` | `evaluate_query_python` |
| `evaluate_query_with_context` | `src/sase/core/query_facade.py` | `evaluate_query_with_context_python` |
| `build_changespec_graph_index` | `src/sase/core/graph_index_facade.py` | `build_changespec_graph_index_python` |
| `transition_changespec_status` | `src/sase/core/status_facade.py` | `transition_changespec_status_python` |

### Temporarily blocked by performance remediation (Phase 8B)

| Operation | Facade | Status |
| --- | --- | --- |
| `evaluate_query_many` | `src/sase/core/query_facade.py` | Phase 8B must either land an amortized Rust path or formally reclassify it as deferred/unported with fresh measurements. Until 8B lands, do not delete `_evaluate_query_many_python`. If 8B succeeds, deletion happens with the rest of the query facade port in 8D; if 8B reclassifies, 8D removes only the dispatcher plumbing and the operation is added to the "intentionally unported" list above. |

## Inventory of backend-selection references

Generated by an explorer pass over the repo on 2026-04-29. Path is repo-relative; line numbers are the position of the
reference (not the position of every match). The inventory covers product code, tests, docs, plans, CI, the Justfile,
and benchmark harnesses; historical plan/research documents that reference the deleted symbols only as Phase 6/7 history
are noted so 8F leaves them alone unless they are wired into runnable code.

### `dispatch` (the legacy backend dispatcher)

- Product (8C-8E to remove the call sites; 8F to delete the function):
  - `src/sase/core/backend.py:138` — definition.
  - `src/sase/core/parser_facade.py:21,91`
  - `src/sase/core/agent_scan_facade.py:56,590`
  - `src/sase/core/query_facade.py:30,65,75,89,103,163`
  - `src/sase/core/graph_index_facade.py:18,25`
  - `src/sase/core/status_facade.py:35,118,134,167,194`
  - `src/sase/core/git_query_facade.py:38,146,189,266,308,350`
- Tests (rewrite/delete in 8D-8F):
  - `tests/test_core_backend.py:137,150,162,174,194`
  - `tests/test_core_dual_run.py:206,236`
  - `tests/test_core_golden.py:481,526,558,572`
  - `tests/test_core_facade/test_backend_contract.py:99,129,162,191`
  - `tests/test_commit_workflow_checkpointing.py:273,293`

### `load_rust_extension` and `is_rust_available`

- Product (8D-8E will switch to `require_rust_extension` / `require_rust_binding`; 8F deletes the legacy helpers):
  - `src/sase/core/backend.py:109,125` (definitions)
  - `src/sase/core/parser_facade.py:21,45,84`
  - `src/sase/core/agent_scan_facade.py:56,551,584`
  - `src/sase/core/query_facade.py:30,47,59,135,157`
  - `src/sase/core/status_facade.py:35,64,77,98,112,128,161`
  - `src/sase/core/git_query_facade.py:38,110,140,165,183,227,260,282,301,325,344`
  - `src/sase/core/health.py:36,115` (`load_rust_extension` only — see Phase 8C health rewrite).
- Tests / benchmarks (rewrite or replace with strict-loader probes in 8D-8F):
  - `tests/test_core_backend.py:21,22,113,114,123,124`
  - `tests/test_core_git_query.py:298`
  - `tests/perf/bench_core_parse.py:58,59,188,189`
  - `tests/perf/bench_core_query.py:53,139,204,291`
  - `tests/perf/bench_agent_scan.py:111,346`
  - `tests/perf/bench_status_state_machine.py:69,365`
  - `tests/perf/bench_workflow_complete.py:38,162`

### `RustBackendUnavailableError`

- Product (8F deletes the class; until then, error text references in docstrings stay green):
  - `src/sase/core/backend.py:62,179,184` (class + raise + message)
  - `src/sase/core/__init__.py:34` (docstring)
  - `src/sase/core/git_query_facade.py:28` (docstring)
  - `src/sase/core/status_facade.py:13,155` (docstrings)
- Tests (8F deletes parity-style assertions; per-facade tests under `tests/test_core_facade/test_*.py` lose the
  shipped/unshipped contract pin, replaced by golden-contract assertions in 8D-8E):
  - `tests/test_core_backend.py:16,161`
  - `tests/test_core_git_query.py:27,455,459,479,481`
  - `tests/test_core_agent_scan.py:40,445`
  - `tests/test_core_dual_run.py:228`
  - `tests/test_core_facade/test_backend_contract.py:36,98`
  - `tests/test_core_facade/test_parser.py:19,111`
  - `tests/test_core_facade/test_query.py:17,106,146,211`
  - `tests/test_core_facade/test_status.py:16,52,54`
- Docs (8G rewrite):
  - `docs/rust_backend.md:18,52,126,161,167-178,351,486,492,539,544,586,590,628`
- Plans / research: occurrences in `plans/202604/rust_backend_phase4_*` through
  `rust_backend_phase7_*` handoffs are historical and stay as Phase 6/7 history per the Phase 8 plan.

### `get_active_backend`, `is_dual_run_enabled`, `get_backend_display`, `BackendDisplay`, `Backend`, `DEFAULT_BACKEND`

- Product (8C rewires health/UI; 8F deletes the symbols):
  - `src/sase/core/backend.py:38,46,53,66,83,89` (definitions)
  - `src/sase/core/health.py:30-37,106,107` (8C)
  - `src/sase/ace/tui/widgets/backend_indicator.py:8,15,20` (8C)
- Tests (8C rewrites; 8F deletes the rest):
  - `tests/test_core_backend.py:18,19,20,28,34,39,44,50,57,67,77,86,92,97`
  - `tests/test_backend_indicator.py:7,8,9,10,17,18,29,30,39,40,50,58,59`

### `SASE_CORE_BACKEND` (env var string)

- Product (8C-8E remove the env-controlled behavior in dispatched call sites; 8F deletes parsing entirely):
  - `src/sase/core/backend.py:55,72,80,184` (definition + uses + error text)
  - `src/sase/core/health.py:31,126,128` (8C health rewrite)
- Tests (rewrite or delete during the corresponding phase):
  - `tests/test_core_backend.py:11,27,28,33,34,38,39,43,44,48,50,54,55,58,64,74,128,129,141,142,156,161,168,185,186`
  - `tests/test_backend_indicator.py:8,17,18,29,30,39,40,58,59`
  - `tests/test_core_git_query.py:24,330,344,410,457,473`
  - `tests/test_core_agent_scan.py:37,75,76,444`
  - `tests/test_core_dual_run.py:11,198,231`
  - `tests/test_core_golden.py:466,474,508,517,560`
  - `tests/test_core_health.py:13,63,64,80,81,97,98,116,117,135,136,153,154,168,169,187,188,200`
  - `tests/test_core_parity_smoke.py:25`
  - `tests/test_query_parser.py:12`
  - `tests/test_agent_names_workflow.py:10`
  - `tests/conftest.py:15`
  - `tests/ace/changespec/test_snapshot_cache.py:14,61`
  - `tests/perf/bench_core_parse.py:56,157,159,161,165`
  - `tests/perf/bench_agent_scan.py:111`
  - `tests/perf/bench_status_state_machine.py:69`
  - `tests/perf/bench_workflow_complete.py:38,162`
- CI / Justfile (8F):
  - `.github/workflows/ci.yml:71,106,115,133`
  - `.github/workflows/publish.yml:41,53,54`
  - `Justfile:210`
- Docs (8G):
  - `docs/rust_backend.md:12,13,16,39,52,...`
- Plans:
  - `plans/202604/rust_backend_phase6_default_rust.md`
  - `plans/202604/github_actions_core_backend_env_isolation.md:29,31,37` (active workflow; 8F should follow up).

### `SASE_CORE_DUAL_RUN` (env var string)

- Product (8F deletes the dual-run module + env var):
  - `src/sase/core/backend.py:9,56,85,164,187`
  - `src/sase/core/dual_run.py:3` (and the rest of the module)
  - `src/sase/core/__init__.py:8,23` (docstrings)
  - Docstring-only refs in `git_query_facade.py:29,136`, `status_facade.py:10,19,158`, `query_facade.py:154`.
- Tests:
  - `tests/conftest.py:15,16`
  - `tests/test_core_backend.py:13,54,55,75,85,86,91,92,96,97,141,156,185,186,194`
  - `tests/test_backend_indicator.py:9,17,18,30,40,59`
  - `tests/test_core_git_query.py:25,494,537`
  - `tests/test_core_agent_scan.py:38,76,494,522`
  - `tests/test_core_dual_run.py:12,197,226,231`
  - `tests/test_core_golden.py:467,474,509,517,560`
  - `tests/test_core_health.py:14,64,81,98,117,136,154,169,188,200`
  - `tests/test_core_parity_smoke.py:25`
  - `tests/perf/bench_core_parse.py:57,169,171,173,177`
  - `tests/perf/bench_workflow_complete.py:38,102`
  - `tests/test_core_facade/test_backend_contract.py:147,180`
  - `tests/test_core_facade/test_status.py:96,261`
  - `tests/test_core_facade/test_parser.py:124`
  - `tests/test_core_facade/test_query.py:221,223`
- CI / Justfile (8F):
  - `.github/workflows/ci.yml:137,164`
  - `.github/workflows/publish.yml:41`
  - `Justfile:297`
- Docs (8G): `docs/rust_backend.md:56,123,223,345,415,455,487,496,560`.

### `core_dual_run.jsonl` and `tests/parity/dual_run_parity.py`

- Product: `src/sase/core/dual_run.py:5,42,48,73,82,97,121` (the JSONL writer); docstring refs in
  `backend.py:10` and `git_query_facade.py:31`.
- Tests:
  - `tests/parity/dual_run_parity.py:243` (8F deletes this file along with `just parity-check`).
  - `tests/test_core_git_query.py:492,535`
  - `tests/test_core_agent_scan.py:484,520`
  - `tests/test_core_dual_run.py:34`
  - Same per-facade backend-contract tests already listed under `SASE_CORE_DUAL_RUN`.
- CI: `.github/workflows/ci.yml:164` (parity job).
- Docs: `docs/rust_backend.md:188,346,455,488,541` (rewritten in 8G).

### Health module specifics

`src/sase/core/health.py` is on the Phase 8C rewrite list. Phase 8A intentionally did not extract any preparatory
helper out of it because the rewrite is small enough that the change should land in one move (the import set will
collapse from `Backend, get_active_backend, is_dual_run_enabled, load_rust_extension` to `require_rust_extension` plus
`require_rust_binding("parse_query")`, and `BackendHealthReport` loses `backend`, `dual_run`, and `rust_required`
fields). The strict loader is in place; 8C should adopt it directly.

## Verification

```
just install
just check
.venv/bin/python -m pytest tests/test_core_rust.py -x
```

All commands ran clean. The new module has no public consumers yet; the dispatcher is unchanged, so the existing backend
contract tests (`tests/test_core_facade/test_backend_contract.py`) still pin the Phase 6/7 contract.

## Hand-off notes for Phase 8B

- The strict loader is `from sase.core.rust import require_rust_extension, require_rust_binding`. Phase 8B should use
  it for any new Rust/PyO3 binding it lands (e.g. an amortized `evaluate_query_many` API), so the new code does not
  reintroduce a dependency on `dispatch` or `is_rust_available`.
- Performance baselines and harnesses still run through `SASE_CORE_BACKEND`; do not delete that yet. 8B should record
  its measurements with the existing harnesses, then 8D/8F can convert them once the Phase 7 baseline anchor is no
  longer derived from a Python comparison.
- If 8B chooses the deferred path for `evaluate_query_many`, update the operation-disposition table above (move the
  row from "blocked" to the "intentionally unported" section) in the 8B handoff so 8C and 8D inherit a single source
  of truth.
