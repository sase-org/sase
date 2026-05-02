---
create_time: 2026-04-29 19:14:21
status: done
bead_id: sase-1f
prompt: sdd/prompts/202604/rust_backend_phase8.md
---
# Rust Backend Migration Phase 8: Remove Backend Selection And Python Fallbacks

## Context

`sdd/research/202604/rust_backend_migration.md` says Phases 0-7 are complete. Rust is the default backend for shipped
`sase.core` operations, `sase-core-rs>=0.1.0,<0.2.0` is already a runtime dependency, the Phase 6/7 rollback path still
exists through `SASE_CORE_BACKEND=python`, and Phase 7 installed the performance floor.

Phase 8 is the consolidation pass. The target steady state is:

- no `SASE_CORE_BACKEND` or `SASE_CORE_DUAL_RUN` behavior in product code;
- no global `sase.core.backend.dispatch` layer;
- ported `sase.core` operations call `sase_core_rs` directly through small typed adapters;
- intentionally unported operations call their Python implementations directly and are no longer described as backend
  fallbacks;
- golden tests compare Rust output to recorded contracts rather than comparing two live implementations;
- CI no longer runs an explicit Python-backend matrix or dual-run parity gate.

The shipped Rust-backed operations entering Phase 8 are:

- `parse_project_bytes`
- `parse_query`
- `evaluate_query_many`
- `scan_agent_artifacts`
- `read_status_from_lines`
- `apply_status_update`
- `plan_status_transition`
- `parse_git_name_status_z`
- `parse_git_branch_name`
- `derive_git_workspace_name`
- `parse_git_conflicted_files`
- `parse_git_local_changes`

The intentionally Python-owned surfaces entering Phase 8 are:

- `build_query_context`
- `evaluate_query`
- `evaluate_query_with_context`
- `build_changespec_graph_index`
- `transition_changespec_status`
- host/plugin responsibilities such as subprocess invocation, process liveness, filesystem mutation, and TUI rendering

## Phase 8 Decisions

1. **`sase-core-rs` is hard-required.** `pyproject.toml` already declares it as a runtime dependency. Phase 8 should not
   reintroduce an optional Rust install story for normal `sase` execution. Source contributors with `../sase-core` still
   use `just rust-install` / `just install` to install a local build.
2. **No product fallback env vars.** Remove `SASE_CORE_BACKEND` and `SASE_CORE_DUAL_RUN` from production dispatch,
   health, docs, tests, and workflows. Historical docs may mention them only as Phase 6/7 history.
3. **Keep `sase.core` as the import seam.** Callers should not import `sase_core_rs` directly. Facades remain
   responsible for dataclass/wire conversion and for keeping Python call signatures stable.
4. **Do not strand unported facades.** Rewire query context/per-row eval, graph index, and side-effecting status
   transitions to direct Python calls before deleting the global dispatcher.
5. **`evaluate_query_many` must be resolved before its Python batch implementation is deleted.** Phase 7 recorded a
   routed-path regression from per-call wire conversion. Phase 8 must either land an amortized Rust path that meets the
   performance gate or explicitly reclassify `evaluate_query_many` as deferred/unported in the Phase 8 handoff. The
   preferred outcome is to optimize it and remove the Python batch implementation in this phase.
6. **Tiny normalizers get re-measured after direct Rust wiring.** Phase 7 found status/Git helpers were sub-50 us and
   dominated by dispatcher cost. Deleting the dispatcher changes that equation; Phase 8 should re-run focused
   microbenchmarks after direct Rust imports and only keep Python copies when the direct Rust boundary still regresses
   enough to justify reclassification.

## Non-Goals

- Do not rewrite the Textual TUI, VCS provider subprocess execution, workspace provider, plugin system, or LLM provider
  flow.
- Do not port graph index construction, per-row query evaluation, or full side-effecting status transitions unless a
  subphase explicitly chooses to do so as the narrowest way to unblock Phase 8.
- Do not remove the legacy Python `parse_project_file` API unless a subphase also lands a complete Rust-wire-to-
  `ChangeSpec` conversion and proves all mutation call sites still work. Phase 8's required parser removal target is the
  Python implementation half of the dispatched `parse_project_bytes` core operation.
- Do not delete historical performance artifacts from `plans/202604/perf_artifacts/`; they remain the Phase 7 evidence
  trail.

## Phase Split For Distinct Agent Instances

Each subphase below is intended for a distinct agent instance. Every agent should read this plan,
`sdd/research/202604/rust_backend_migration.md`, `docs/rust_backend.md`,
`plans/202604/rust_backend_phase7_phase7f_handoff.md`, and the previous Phase 8 handoff before editing. Agents should
stay inside their write scope, append a handoff, and not start later phases.

### Phase 8A: Inventory, Contract Freeze, And Direct Loader Foundation

Purpose: make the rest of Phase 8 mechanical by freezing the operation disposition and creating one strict Rust-loading
helper that does not know about backend selection.

Write scope:

- `src/sase/core/backend.py` or a new small module such as `src/sase/core/rust.py`.
- `src/sase/core/health.py` only for preparatory helper extraction, not behavior removal yet.
- focused backend tests under `tests/test_core_backend.py`, `tests/test_core_health.py`, and
  `tests/test_core_facade/test_backend_contract.py`.
- `docs/rust_backend.md` only for a short "Phase 8 in progress" note if needed.
- `plans/202604/rust_backend_phase8_phase8a_handoff.md`.

Work:

- Inventory every import and call site for:
  - `dispatch`
  - `load_rust_extension`
  - `is_rust_available`
  - `RustBackendUnavailableError`
  - `get_active_backend`
  - `is_dual_run_enabled`
  - `SASE_CORE_BACKEND`
  - `SASE_CORE_DUAL_RUN`
- Add a strict Rust extension loader, for example `require_rust_extension()`, that imports `sase_core_rs` and raises a
  normal import/compatibility error if the wheel is missing or stale. This helper should not inspect env vars and should
  be the only supported import path for ported facades.
- Add a binding capability check helper if useful, for example `require_rust_binding("parse_query")`, so direct facades
  can fail with operation-specific text without reimplementing import checks.
- Decide and document the Phase 8 operation disposition:
  - direct Rust now;
  - direct Python because intentionally unported;
  - temporarily blocked by `evaluate_query_many` performance remediation.
- Keep existing behavior green in this subphase. Do not delete `dispatch`, dual-run, or env vars yet.

Exit criteria:

- The handoff lists every product/test/doc/CI reference to backend selection and assigns it to a later subphase.
- A strict Rust loader exists and is tested, while the current dispatcher still works.
- `just check` passes.

### Phase 8B: Resolve The `evaluate_query_many` Regression

Purpose: remove the one known Phase 8 blocker before deleting the Python batch evaluator.

Write scope:

- `../sase-core/crates/sase_core/src/` and `../sase-core/crates/sase_core_py/src/lib.rs` if a new Rust/PyO3 API is
  needed.
- `src/sase/core/query_facade.py` and query wire conversion helpers.
- query performance harnesses under `tests/perf/bench_core_query.py`, `tests/perf/phase7/`, and
  `tests/perf/baselines/phase7_regression_floor.json` only as needed.
- focused query tests under `tests/test_core_facade/test_query.py`, `tests/test_core_query_golden_eval.py`, and related
  golden tests.
- `plans/202604/rust_backend_phase8_phase8b_handoff.md`.

Work:

- Reproduce the Phase 7 regression locally with the smallest stable workload from the Phase 7 artifacts.
- Implement the least invasive amortization strategy. Prefer one of these, in order:
  - a Rust/PyO3 API that accepts a reusable corpus/wire payload and can evaluate multiple queries or repeated filters
    without rebuilding every wire dict on each call;
  - a Python-side cache of JSON-safe wire records keyed by stable object identity plus mutation-safe invalidation if the
    caller repeatedly filters the same `ChangeSpec` list;
  - a direct Rust extraction path that avoids `ChangeSpec -> ChangeSpecWire -> dict` churn if measurement proves it is
    faster and keeps the Python API stable.
- Preserve correctness for ancestry, sibling, status, project, text, comments, mentors, timestamps, and delta filters.
- Re-run the Phase 7 query benchmark and update the regression floor only if the benchmark scenario or anchor changes.
- If the optimized path still cannot beat or match the Python batch path, do not delete `_evaluate_query_many_python`.
  Instead, reclassify `evaluate_query_many` as deferred/unported in the handoff and docs, and adjust later phases to
  remove only backend-selection plumbing around it. That exception must be explicit and justified by numbers.

Exit criteria:

- Preferred: `evaluate_query_many` uses a Rust-backed path whose median is no worse than the existing Python batch path
  on the Phase 7 synthetic workloads, and its Python batch implementation is safe to delete in Phase 8D.
- Acceptable fallback: `evaluate_query_many` is formally removed from the Phase 8 deletion set with fresh measurements,
  direct Python wiring, and docs explaining why the Python implementation remains until a later port.
- `just rust-check`, the focused query tests, and the relevant query benchmark pass.

### Phase 8C: Rewire Unported Facades To Direct Python And Remove Backend Selection From User Surfaces

Purpose: make deletion of `backend.dispatch` safe by removing all Python-fallback uses from unported operations and
turning health/UI surfaces into "Rust core installed" checks rather than backend selectors.

Write scope:

- `src/sase/core/query_facade.py`
- `src/sase/core/graph_index_facade.py`
- `src/sase/core/status_facade.py`
- `src/sase/core/health.py`
- `src/sase/main/core_handler.py` and parser files for `sase core health` if output changes.
- TUI backend indicator files under `src/sase/ace/tui/widgets/` and their tests.
- focused tests for query, graph index, status, health, and backend indicator.
- `plans/202604/rust_backend_phase8_phase8c_handoff.md`.

Work:

- Change intentionally unported operations to direct Python calls:
  - `build_query_context -> build_query_context_python`
  - `evaluate_query -> evaluate_query_python`
  - `evaluate_query_with_context -> evaluate_query_with_context_python`
  - `build_changespec_graph_index -> build_changespec_graph_index_python`
  - `transition_changespec_status -> transition_changespec_status_python`
- Remove backend labels and dual-run state from the TUI. Either remove the backend indicator entirely or replace it with
  a static core-health indicator only if there is a product reason to keep visible status.
- Change `sase core health` so it no longer reports a selected backend or accepts Python mode as healthy without Rust.
  It should verify the installed `sase_core_rs` extension and at least one cheap binding such as `parse_query`.
- Update tests that currently assert explicit Python mode, dual-run mode, or backend display colors.
- Keep `dispatch` available until all ported facades are rewired in later phases.

Exit criteria:

- No unported facade depends on `dispatch` or `rust_unavailable="python"`.
- Product UI/health surfaces no longer describe backend selection as a runtime mode.
- `just check` passes.

### Phase 8D: Direct-Rust Ported Facades And Delete Clear-Win Python Halves

Purpose: remove the Python fallback implementations and dispatcher calls for the high-confidence Rust wins.

Write scope:

- `src/sase/core/parser_facade.py`
- `src/sase/core/agent_scan_facade.py`
- `src/sase/core/query_facade.py` for `parse_query` and, if Phase 8B succeeded, `evaluate_query_many`.
- `tests/test_core_facade/test_parser.py`
- `tests/test_core_facade/test_query.py`
- `tests/test_core_agent_scan.py`
- parser/query/agent-scan golden fixtures and tests as needed.
- `plans/202604/rust_backend_phase8_phase8d_handoff.md`.

Work:

- Replace each facade's `load_rust_extension` / `dispatch` branch with direct calls through the strict Rust loader.
- Delete local Python fallback implementations for these ported operations:
  - `parse_project_bytes` fallback closure in `parser_facade.py`;
  - `scan_agent_artifacts_python` and the marker-walking helpers used only by that fallback;
  - `parse_query_python` routing from the facade, while leaving the Python query parser module available for unported
    per-row evaluation tests if still needed;
  - `_evaluate_query_many_python` only if Phase 8B met the preferred exit criterion.
- Repoint tests away from fake backend selection. Use fake `sase_core_rs` modules or monkeypatched strict loaders to
  prove the adapters shape data correctly.
- Convert parity-style assertions to golden-contract assertions:
  - direct Rust output matches committed JSON/wire expectations;
  - documented `parse_project_bytes.source_span.end_line` behavior remains explicit.

Exit criteria:

- Parser, query parse, and agent scan facades contain no backend selection branches.
- Clear-win Python fallback code for those operations is gone.
- Focused tests and `just check` pass.

### Phase 8E: Direct-Rust Status And Git Helpers, Then Re-Measure Tiny Operations

Purpose: finish direct Rust wiring for the small pure helpers while making the Phase 7 caveat explicit with fresh data.

Write scope:

- `src/sase/core/status_facade.py`
- `src/sase/status_state_machine/field_updates.py` if public wrappers or `*_python` names change.
- `src/sase/core/git_query_facade.py`
- `tests/test_core_facade/test_status.py`
- `tests/test_core_git_query.py`
- `tests/test_core_status_lines.py`
- `tests/perf/bench_status_state_machine.py`
- `tests/perf/bench_git_query_ops.py`
- Phase 7/8 perf artifacts and baselines only if the stable anchor set changes.
- `plans/202604/rust_backend_phase8_phase8e_handoff.md`.

Work:

- Replace status facade dispatch with direct Rust calls for:
  - `read_status_from_lines`
  - `apply_status_update`
  - `plan_status_transition`
- Decide whether to remove or keep `read_status_from_lines_python`, `apply_status_update_python`, and
  `plan_status_transition_python`:
  - remove them if no non-test caller needs them after direct Rust wiring;
  - keep only the functions still required by unported side-effecting status code, and document them as host logic, not
    backend fallback.
- Replace Git query facade dispatch with direct Rust calls for:
  - `parse_git_name_status_z`
  - `parse_git_branch_name`
  - `derive_git_workspace_name`
  - `parse_git_conflicted_files`
  - `parse_git_local_changes`
- Delete Git facade `*_python` implementations if direct Rust remains accepted after focused measurement.
- Re-run status and Git microbenchmarks against the direct-Rust wrappers. If direct Rust is still materially worse for a
  tiny helper, explicitly reclassify that helper as Python-owned host logic rather than leaving a hidden backend switch.

Exit criteria:

- Status and Git facades have no `dispatch` calls and no env-var backend behavior.
- Any retained Python helper has a non-backend reason to exist and is documented in the handoff.
- `just phase7-perf-check` still passes or is updated with a justified Phase 8 baseline change.
- `just check` and `just rust-check` pass.

### Phase 8F: Delete Dual-Run, Backend Dispatcher, CI Matrix, And Historical Tests

Purpose: remove the now-unused Phase 6/7 safety rails after all facades have been rewired.

Write scope:

- `src/sase/core/backend.py`
- `src/sase/core/dual_run.py`
- `src/sase/core/__init__.py`
- `tests/test_core_backend.py`
- `tests/test_core_dual_run.py`
- `tests/test_core_facade/test_backend_contract.py`
- `tests/parity/dual_run_parity.py`
- `Justfile`
- `.github/workflows/ci.yml`
- `.github/workflows/publish.yml`
- performance harnesses that still expose Python-vs-Rust backend modes.
- `plans/202604/rust_backend_phase8_phase8f_handoff.md`.

Work:

- Delete `dual_run.py` and tests that only validate dual-run record writing.
- Delete `dispatch`, `Backend`, `DEFAULT_BACKEND`, `RustBackendUnavailableError`, and env-var parsing. If a small Rust
  import helper was introduced in `backend.py`, move it to a better-named module before deleting backend-specific names.
- Remove `tests/parity/dual_run_parity.py` and `just parity-check`.
- Remove `test-python-backend` and `parity-gate` from CI.
- Update install smoke so it checks only the required Rust extension health.
- Update performance harnesses so their default mode is current Rust behavior. Historical comparison scripts can remain
  if they do not depend on deleted product env vars and are clearly marked as archival/manual.
- Run
  `rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|RustBackendUnavailableError|is_rust_available|sase.core.backend|dual_run"`
  and resolve all product references. Historical docs/plans may retain references only when clearly dated.

Exit criteria:

- `rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|is_rust_available" src/` returns nothing.
- No facade imports `sase.core.backend`.
- The normal CI workflow has no explicit Python-backend or dual-run parity jobs.
- `just check` passes.

### Phase 8G: Golden Contract, Documentation, And Close-Out

Purpose: make the post-Phase 8 state understandable and record what was deleted.

Write scope:

- `docs/rust_backend.md`
- `sdd/research/202604/rust_backend_migration.md`
- golden-contract tests and fixtures under `tests/core_golden/`, `tests/agent_scan_golden/`, and `tests/test_core_*`.
- `tests/perf/baselines/phase7_regression_floor.json` if Phase 8 changed benchmark anchors.
- `plans/202604/rust_backend_phase8_phase8g_handoff.md`.

Work:

- Rewrite `docs/rust_backend.md` to describe the steady state:
  - Rust core is required;
  - no backend env vars;
  - `sase core health` checks the installed Rust extension;
  - rollback is a `sase-core-rs` wheel/package fix or reverting Phase 8 PRs, not a per-user env var.
- Update `sdd/research/202604/rust_backend_migration.md` with Phase 8 complete status, operation disposition, and any
  retained Python-owned exceptions.
- Replace live Python/Rust parity language with golden-contract language. The golden corpus is the compatibility seam
  for parser/query/status/git/agent-scan output after Phase 8.
- Record final verification:
  - `just install`
  - `just check`
  - `just rust-check`
  - `just phase7-perf-check`
  - `sase core health --json`
  - any focused Phase 8 query/status/Git benchmarks used to justify deletion decisions
- Add a close-out checklist with exact `rg` commands proving backend env vars and dispatch plumbing are gone from
  `src/`.

Exit criteria:

- Phase 8 is marked complete in docs and research.
- The close-out handoff names every Python implementation that was deleted and every Python-owned operation that
  remains.
- Full verification is green, or any skipped command has a concrete environment reason and a follow-up owner.

## Cross-Phase Verification Rules

Every subphase that edits this repo should run at least:

```bash
just install
just check
```

Subphases touching `../sase-core` should also run:

```bash
just rust-check
```

Subphases touching performance-sensitive facades should run the focused benchmark first, then `just phase7-perf-check`
before handoff.

Because this repo uses ephemeral workspaces, run `just install` before other `just` targets in each agent instance.

## Final Phase 8 Completion Checklist

- [ ] No production code reads `SASE_CORE_BACKEND`.
- [ ] No production code reads `SASE_CORE_DUAL_RUN`.
- [ ] No facade imports `sase.core.backend`.
- [ ] `src/sase/core/dual_run.py` is deleted.
- [ ] `tests/parity/dual_run_parity.py` and `just parity-check` are deleted.
- [ ] CI has no explicit Python-backend test job and no dual-run parity job.
- [ ] `sase core health --json` fails if `sase_core_rs` is missing or stale.
- [ ] Golden-contract tests cover parser, query, agent scan, status, and Git helper output without live Python/Rust
      parity.
- [ ] `evaluate_query_many` has either an accepted Rust path or an explicit documented deferral.
- [ ] `docs/rust_backend.md` documents post-Phase 8 rollback as a wheel/package fix, not an env-var workaround.
