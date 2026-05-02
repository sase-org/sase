---
create_time: 2026-04-29 17:52:06
status: done
bead_id: sase-1e
prompt: sdd/prompts/202604/rust_backend_phase7.md
---

# Rust Backend Migration Phase 7: Measurement, Documentation, And Regression Floor

## Context

`sdd/research/202604/rust_backend_migration.md` says Phases 0-6 are complete. Rust is now the default backend for every
shipped `sase.core` operation, `sase-core-rs` is a runtime dependency, CI exercises default Rust plus explicit Python,
and `SASE_CORE_BACKEND=python` remains the temporary rollback path through Phase 7.

Phase 7 is deliberately not another Rust port. It is the measurement and supportability pass that must happen before
Phase 8 removes the Python implementations. The work should prove, with checked-in artifacts, what users actually gained
from the default flip and should install a regression floor so the win cannot erode after the escape hatch is deleted.

Shipped operations that need Phase 7 coverage:

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

User-visible surfaces that need end-to-end coverage:

- cold `sase ace` startup with `SASE_TUI_TRACE=1`
- cold `sase agents status -j` listing on synthetic and real home-tree workloads
- `sase run` startup up to the provider boundary, using a deterministic no-network provider/stub

## Goals

1. Capture repeatable default-Rust vs explicit-Python measurements for all shipped Rust-backed operations.
2. Capture end-to-end TUI/CLI timings where the backend choice is only one part of the total user cost.
3. Store raw JSON artifacts under `plans/202604/perf_artifacts/` and summarize the results in docs/research.
4. Codify a CI regression floor for a stable synthetic subset, with a separate scheduled/manual path for slower
   end-to-end workloads.
5. Update the user-facing Rust backend docs so they read like the current product state, not a migration roadmap.

## Non-Goals

- Do not remove Python implementations, backend dispatch, `SASE_CORE_BACKEND`, or `SASE_CORE_DUAL_RUN`. That is Phase 8.
- Do not port graph index, per-row query helpers, full status transitions, VCS subprocess behavior, or any TUI rendering
  logic to Rust during Phase 7.
- Do not run live LLM providers as part of benchmarks. `sase run` startup measurement must use a deterministic local
  stub or stop at the provider-invoke boundary.
- Do not make a noisy absolute-time PR gate for interactive TUI/home-tree workloads. Those belong in scheduled/manual
  measurement unless the harness proves stable enough for CI.

## Phase Split For Distinct Agent Instances

Each subphase below is intended for a separate agent instance. Every agent should read this plan,
`sdd/research/202604/rust_backend_migration.md`, `docs/rust_backend.md`, and the previous Phase 7 handoff before editing.
Each agent must stay inside its write scope and leave later phases alone except for appending a handoff.

### Phase 7A: Measurement Contract And Artifact Schema

Purpose: make the Phase 7 measurements comparable before anyone starts collecting headline numbers.

Write scope:

- `tests/perf/` helper modules or a new `tests/perf/phase7/` helper package.
- `Justfile` only for new benchmark/check targets.
- `plans/202604/perf_artifacts/README.md` or a short schema note if useful.
- `plans/202604/rust_backend_phase7_phase7a_handoff.md`.

Work:

- Define the common artifact metadata shape used by every Phase 7 report:
  - git SHA and dirty flag;
  - command line / harness name;
  - timestamp;
  - Python version, platform, machine, processor;
  - `sase_core_rs` import path and version when available;
  - selected backend and whether the backend was default or explicit;
  - run count, warmup count, workload label, median/p95/min/max.
- Add a small helper for computing ratios and speedups from existing benchmark JSON shapes. Prefer adapting existing
  JSON rather than rewriting every benchmark.
- Add a `just` target for the eventual Phase 7 check path, but keep it as a wrapper/smoke until Phase 7E wires the real
  regression floor.
- Decide the artifact naming convention. Recommended:
  `plans/202604/perf_artifacts/rust_backend_phase7_<surface>_<backend_or_summary>.json`.
- Run smoke-sized versions of the helper against at least two existing benchmark reports.

Exit criteria:

- Later agents can produce consistently shaped JSON without inventing their own metadata.
- The handoff lists exact artifact file names expected from Phases 7B and 7C.

### Phase 7B: Core Operation Microbenchmarks

Purpose: measure every shipped Rust-backed operation under explicit Python and default Rust.

Write scope:

- Existing `tests/perf/bench_core_parse.py`, `bench_core_query.py`, `bench_agent_scan.py`,
  `bench_status_state_machine.py`, `bench_git_query_ops.py`, and `bench_workflow_complete.py` only if the harnesses need
  small metadata/output fixes.
- `plans/202604/perf_artifacts/rust_backend_phase7_core_*.json`.
- `plans/202604/rust_backend_phase7_phase7b_handoff.md`.

Work:

- Run the existing core benchmarks with enough samples to get stable medians:
  - `just bench-core --runs 20 --warmup 3 --num-specs 200 --output ...`
  - `just bench-query --runs 20 --warmup 3 --spec-sizes 100,1000,10000 --output ...`
  - `just bench-agent-scan --projects 6 --per-project 200 --runs 10 --warmup 2 --include-home --output ...`
  - `just bench-status-state-machine --runs 200 --warmup 20 --num-specs 200 --output ...`
  - `just bench-git-query-ops --runs 200 --warmup 20 --output ...`
  - `tests/perf/bench_workflow_complete.py --projects 6 --per-project 200 --runs 10 --warmup 2 --output ...`
- For harnesses that already compare both backends in one process, preserve that shape. For Git query ops, run once with
  `SASE_CORE_BACKEND=python` and once with default Rust or `SASE_CORE_BACKEND=rust`, then produce a summary JSON using
  the Phase 7A helper.
- Verify every shipped operation appears in either a direct scenario or a clearly mapped aggregate scenario.
- Record negative results honestly: status planner / Git parser wins may be too small to matter because they are cheap
  or subprocess-dominated.

Exit criteria:

- Raw core-operation JSON artifacts are checked in under `plans/202604/perf_artifacts/`.
- The handoff contains a compact table of median Rust/Python ratios and calls out any regression or noisy result.

### Phase 7C: End-To-End TUI And CLI Measurements

Purpose: measure user-facing surfaces, not just facade microtimings.

Write scope:

- `tests/perf/bench_tui_trace.py` only for Phase 7 metadata/backend comparison fixes.
- A new focused CLI startup benchmark under `tests/perf/` if needed.
- `plans/202604/perf_artifacts/rust_backend_phase7_e2e_*.json`.
- `plans/202604/rust_backend_phase7_phase7c_handoff.md`.

Work:

- Capture `sase ace` cold-open timings with `SASE_TUI_TRACE=1` under both backends. Reuse the existing Pilot-based
  harness for synthetic fixtures, and add a documented manual/home-tree run if fully automated home-tree TUI startup is
  too environment-sensitive.
- Capture `sase agents status -j` cold listing as a subprocess so import/startup cost is included:
  - synthetic `HOME` with a generated `~/.sase/projects` tree;
  - real home tree when present, with user-private paths summarized or sanitized in artifacts.
- Capture `sase run` startup through a deterministic path:
  - no live network;
  - no real provider invocation;
  - either register a local test provider for the subprocess or benchmark the in-process `run_query()` path with
    provider invocation mocked and explicitly label the boundary.
- For every end-to-end workload, compare explicit Python vs default Rust and include sample size, median, p95, and
  workload size.
- Sanitize artifacts so no private prompt text, project path, or home directory leaks into committed JSON.

Exit criteria:

- There is at least one realistic end-to-end median for TUI cold open, `sase agents`, and `sase run` startup.
- The handoff states which numbers are synthetic, which are home-tree, and which are manual/scheduled-only.

### Phase 7D: Documentation And Research Narrative

Purpose: make the measured result understandable to users and future maintainers.

Write scope:

- `docs/rust_backend.md`.
- `sdd/research/202604/rust_backend_migration.md` or a new `sdd/research/202604/rust_backend_phase7_performance.md`.
- `plans/202604/rust_backend_phase7_phase7d_handoff.md`.

Work:

- Add a `Performance` section to `docs/rust_backend.md` with:
  - workstation/profile metadata;
  - sample sizes;
  - median tables for core operations and end-to-end surfaces;
  - links to raw JSON artifacts in `plans/202604/perf_artifacts/`;
  - a concise "where Rust helps" / "where Rust does not help" explanation.
- Add or update the research record with the realized speedups, including negative results and workload-size caveats.
- Add the Phase 7 support note requested by the migration doc:
  - how to confirm backend mode with `sase core health`;
  - where dual-run logs live;
  - what a wheel-load failure looks like;
  - how to temporarily use `SASE_CORE_BACKEND=python` during the Phase 7 window.
- Keep Phase 8 language forward-looking: Python removal is not part of this phase.

Exit criteria:

- `docs/rust_backend.md` has a current, cited performance story and no longer treats Phase 7 as merely upcoming.
- The research record gives future Phase 8 and future-port agents one canonical place to cite the outcome.

### Phase 7E: CI Regression Floor

Purpose: turn the Phase 7 numbers into an enforceable guardrail without making CI flaky.

Write scope:

- New baseline file under `tests/perf/baselines/` or `plans/202604/perf_artifacts/`.
- New checker script under `tests/perf/`.
- `.github/workflows/ci.yml` and/or a new scheduled/manual workflow.
- `Justfile`.
- `plans/202604/rust_backend_phase7_phase7e_handoff.md`.

Work:

- Choose the stable subset for PR CI. Recommended required set:
  - parser synthetic medium;
  - query parse + `evaluate_query_many` at 1k specs;
  - agent-scan synthetic tree;
  - status line helpers on synthetic 200 specs;
  - Git parser synthetic medium, not subprocess end-to-end.
- Derive tolerance from the Phase 7B/7C data. Start with a conservative relative floor such as "Rust median must not be
  more than 25-35% slower than the recorded Phase 7 Rust median, and must not regress below explicit Python for
  parser/query/agent-scan scenarios where Phase 7 showed Rust faster." Tighten only if the data is stable.
- Keep end-to-end TUI/home-tree checks in a scheduled or `workflow_dispatch` job unless they prove stable in CI.
- Add a local target such as `just phase7-perf-check` that runs the stable synthetic subset and invokes the checker.
- Upload perf artifacts on failure so regressions are inspectable.

Exit criteria:

- CI has a benchmark floor for the stable subset.
- Slow/manual end-to-end measurement has a documented command or workflow.
- The handoff documents exact thresholds and why they are not tighter.

### Phase 7F: Verification And Close-Out

Purpose: prove the measurement/docs/regression-floor work is integrated and Phase 8 has a clean starting point.

Write scope:

- `plans/202604/rust_backend_phase7_phase7f_handoff.md`.
- Small doc/test fixes required by final verification.

Work:

- Run:
  - `just install`
  - `just phase7-perf-check` or the final target from Phase 7E
  - `just parity-check`
  - `just check`
  - `SASE_CORE_BACKEND=python just test`
  - `just rust-check` when `../sase-core` is present
- Re-run `sase core health --json` and `SASE_CORE_BACKEND=python sase core health --json`.
- Confirm all Phase 7 artifacts are committed and docs link to the actual file names.
- Update `sdd/research/202604/rust_backend_migration.md` to mark Phase 7 complete if Phase 7D did not already do so.
- Write the Phase 7F handoff with:
  - final artifact list;
  - verification commands and results;
  - any known measurement caveats;
  - explicit Phase 8 readiness checklist.

Exit criteria:

- Every routed operation has a documented before/after median on a realistic or synthetic workload.
- End-to-end surfaces have documented medians and caveats.
- Regression floor is wired.
- Phase 8 can begin without needing to rediscover Phase 7's measurement setup.

## Suggested Dependency Order

1. Phase 7A must land first.
2. Phases 7B and 7C can run in parallel after 7A.
3. Phase 7D depends on 7B and 7C.
4. Phase 7E depends on 7B, and should incorporate 7C only for scheduled/manual checks.
5. Phase 7F depends on 7D and 7E.

## Verification Baseline For Every Agent

Agents that edit code should run focused tests for their write scope. Any agent that changes this repo's code should run
`just install` before checks in this workspace and `just check` before handing off. Agents that only add measurement
artifacts/docs may run the relevant markdown/benchmark smoke plus `just fmt-md-check` if Markdown formatting changed,
but the final Phase 7F agent owns full-suite verification.
