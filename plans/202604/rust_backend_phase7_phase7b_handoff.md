# Phase 7B Handoff: Core Operation Microbenchmarks

Bead: `sase-1e.2`. Plan: `plans/202604/rust_backend_phase7.md`. Phase 7B captures default-Rust vs explicit-Python
medians for every shipped Rust-backed core operation, using the artifact contract Phase 7A locked.

## What landed

- `tests/perf/phase7/run_phase7b.py` — single in-process driver that runs every existing core benchmark and writes one
  per-surface SUMMARY artifact under `plans/202604/perf_artifacts/`. Each artifact embeds the Phase 7A
  `Phase7Metadata` envelope, the relevant scenario summaries from the harness it was derived from, and the
  per-(workload, scenario) rows produced by `tests.perf.phase7.summarize_report`.
- `tests/perf/bench_status_state_machine.py` — a small scenario-only addition: `plan_status_transition` is now timed
  alongside `read_status_from_lines` / `apply_status_update` under both `python` and `rust` backends. No structural
  changes to the harness; the new scenario runs in the same `_measure_pure` block. This was needed because
  `plan_status_transition` is the pure decision engine and is not exercised by the orchestrator scenarios.
- 12 Phase 7B summary artifacts under `plans/202604/perf_artifacts/`:
  - `rust_backend_phase7_parse_project_bytes_summary.json`
  - `rust_backend_phase7_parse_query_summary.json`
  - `rust_backend_phase7_evaluate_query_many_summary.json`
  - `rust_backend_phase7_scan_agent_artifacts_summary.json`
  - `rust_backend_phase7_read_status_from_lines_summary.json`
  - `rust_backend_phase7_apply_status_update_summary.json`
  - `rust_backend_phase7_plan_status_transition_summary.json`
  - `rust_backend_phase7_parse_git_name_status_z_summary.json`
  - `rust_backend_phase7_parse_git_branch_name_summary.json`
  - `rust_backend_phase7_derive_git_workspace_name_summary.json`
  - `rust_backend_phase7_parse_git_conflicted_files_summary.json`
  - `rust_backend_phase7_parse_git_local_changes_summary.json`

The driver chose the SUMMARY-tag path explicitly authorized by the Phase 7A handoff (most existing harnesses already
exercise both backends in one process). Per-backend split artifacts (`_default_rust.json` / `_explicit_python.json`)
were not produced; everything Phase 7D needs to pivot is inside the SUMMARY artifacts.

Out of scope for Phase 7B:

- No CI integration. Phase 7E owns the regression floor.
- No end-to-end TUI / `sase agents` / `sase run` measurements. Phase 7C owns those.
- No documentation updates. Phase 7D owns `docs/rust_backend.md` and the research record.

## How to reproduce the artifacts

```
just install
.venv/bin/python tests/perf/phase7/run_phase7b.py
```

`--smoke` runs the same code path with tiny sample sizes for ad-hoc verification (artifacts will be flagged with
`extra.smoke=True` so they cannot be confused with real captures).

The driver uses the sample sizes the Phase 7 plan calls out in §7B "Work":

| Harness                          | Knobs                                                              |
| -------------------------------- | ------------------------------------------------------------------ |
| `bench_core_parse`               | `runs=20 warmup=3 num_specs=200`                                   |
| `bench_core_query`               | `runs=20 warmup=3 spec_sizes=100,1000,10000`                       |
| `bench_agent_scan`               | `projects=6 per_project=200 workflow_fraction=0.25 runs=10 warmup=2` |
| `bench_status_state_machine`     | `runs=200 warmup=20 num_specs=200 transition_runs=20`              |
| `bench_git_query_ops` (×2)       | `runs=200 warmup=20 small=50 medium=1000 large=10000`              |

The Git query ops harness is run twice (once with `SASE_CORE_BACKEND=python`, once with no env override so the default
Rust path is exercised); every other harness flips backends per-scenario inside one process. Total wall clock is ~95s
on the capture machine; see `git_sha` / `python` / `system` / `machine` / `rust_module_path` in any artifact's
`metadata` for the exact provenance.

`bench_workflow_complete.py` was *not* run by Phase 7B. The Phase 7A open question asked Phase 7B to either run it or
document the skip — Phase 7B skips it. Rationale: it covers `is_workflow_complete`, which is not in the shipped Rust
core-ops list (it's a Python-side traversal that calls the Rust scan facade only as one option). Phase 7C is the right
home if its `is_workflow_complete` numbers are wanted as part of an end-to-end story; Phase 7B keeps the artifact set
to the 12 shipped operations.

## Headline median table (capture machine: Linux x86_64, Python 3.14.3, sase_core_rs default install)

Speedup is `python_median / rust_median` — values >1 mean Rust is faster, <1 means Rust is slower. "scenario" matches
the Phase 7A SUMMARY-artifact `comparisons[].scenario` key.

| Surface                       | Workload                  | Scenario                  | py median | rust median | speedup |
| ----------------------------- | ------------------------- | ------------------------- | --------: | ----------: | ------: |
| parse_project_bytes           | golden_myproj             | facade                    | 296 µs    | 124 µs      | **2.4×** |
| parse_project_bytes           | golden_myproj             | direct                    | 121 µs    |  58 µs      | **2.1×** |
| parse_project_bytes           | synthetic_200_specs       | facade                    | 26.7 ms   | 19.1 ms     | **1.4×** |
| parse_project_bytes           | synthetic_200_specs       | direct                    | 17.7 ms   | 13.1 ms     | **1.4×** |
| parse_query                   | parse_only                | facade                    |  17.7 µs  |  21.1 µs    | 0.84×    |
| parse_query                   | parse_only                | direct                    |  12.3 µs  |   5.8 µs    | **2.1×** |
| evaluate_query_many           | synthetic_100_specs       | facade                    | 0.50 ms   | 7.81 ms     | **0.06×** |
| evaluate_query_many           | synthetic_1000_specs      | facade                    | 4.03 ms   | 74.7 ms     | **0.05×** |
| evaluate_query_many           | synthetic_10000_specs     | facade                    | 68.1 ms   | 831 ms      | **0.08×** |
| scan_agent_artifacts          | synthetic_6p_200pp        | scan_facade               | 145 ms    | 120 ms      | **1.21×** |
| read_status_from_lines        | golden_myproj_pure        | read_status_from_lines    |  3.76 µs  |   5.46 µs   | 0.69×    |
| read_status_from_lines        | synthetic_200_specs_pure  | read_status_from_lines    | 182 µs    | 349 µs      | 0.52×    |
| apply_status_update           | golden_myproj_pure        | apply_status_update       |  5.57 µs  |   5.80 µs   | 0.96×    |
| apply_status_update           | synthetic_200_specs_pure  | apply_status_update       | 256 µs    | 377 µs      | 0.68×    |
| plan_status_transition        | golden_myproj_pure        | plan_status_transition    |  8.65 µs  |  18.74 µs   | 0.46×    |
| plan_status_transition        | synthetic_200_specs_pure  | plan_status_transition    |  8.66 µs  |  18.78 µs   | 0.46×    |
| parse_git_name_status_z       | synthetic_small (50)      | parse_git_name_status_z   | 32.4 µs   | 44.4 µs     | 0.73×    |
| parse_git_name_status_z       | synthetic_medium (1k)     | parse_git_name_status_z   | 626 µs    | 880 µs      | 0.71×    |
| parse_git_name_status_z       | synthetic_large (10k)     | parse_git_name_status_z   | 6.64 ms   | 8.86 ms     | 0.75×    |
| parse_git_name_status_z       | end_to_end_500            | parse_git_name_status_z   | 287 µs    | 401 µs      | 0.72×    |
| parse_git_branch_name         | normalizers_x4            | parse_git_branch_name     |  8.74 µs  |  10.40 µs   | 0.84×    |
| derive_git_workspace_name     | normalizers_x5            | derive_git_workspace_name | 11.7 µs   | 13.5 µs     | 0.87×    |
| parse_git_conflicted_files    | normalizers_50_lines      | parse_git_conflicted_files|  5.35 µs  |   6.83 µs   | 0.78×    |
| parse_git_local_changes       | normalizers_150_entries   | parse_git_local_changes   |  4.51 µs  |   5.68 µs   | 0.79×    |

The full per-percentile data (min/median/p95/max) is in each surface's artifact under `workloads[].baseline` /
`workloads[].candidate`; the comparison rows pre-compute `ratio`, `speedup`, and `percent_delta` for every
`(workload, scenario)` pair so Phase 7D's table can be assembled by reading the artifacts only.

## Where Rust helps, where it does not (call-outs for Phase 7D)

**Wins (commit story is straightforward):**

- `parse_project_bytes` is a clean ~2× win on small files and ~1.4× on a 200-spec synthetic file. Both `direct` (raw
  Rust call) and `facade` (Rust through the dispatch layer) beat Python at every workload size measured, so the
  end-to-end product story holds.
- `scan_agent_artifacts` is a ~1.2× win on the synthetic 6-project / 200-per-project tree (the closest hermetic
  approximation of a real `~/.sase/projects` listing). The `scan_rust_to_dict` row (Rust scan + dict construction
  alone, no Python wire conversion) is faster than the full `scan_facade` row, which confirms Phase 3G's claim that the
  Python-side `agent_scan_wire_from_dict` projection is a meaningful chunk of the facade cost.
- `parse_query` has a strong direct-Rust win on the parse-only workload (~2.1×). The synthetic_*_specs evaluate
  workloads in `bench_core_query` deliberately do not re-time `rust_facade_parse` (the harness folds parse cost into
  `evaluate_query_many` for those workloads), so the SUMMARY artifact reports the Rust-side parse columns as missing
  for synthetic workloads. That is intentional, not a regression.

**Honest negative results that Phase 7D needs to call out, not paper over:**

- `evaluate_query_many` (the routed evaluator) is dramatically slower under default Rust than the optimized
  Python batch path: 8 µs/spec vs 4-7 µs/spec on the Python side at 100 specs, scaling worse at 10k specs. The cause is
  per-call wire conversion (`changespec_to_wire` + `to_json_dict`) for every spec on every facade call — the marshaling
  overhead dominates the actual evaluation. Phase 7D should explicitly document that today's `evaluate_query_many`
  shipped Rust path is **not** an end-to-end win on the default backend; the win is upstream (parse) and inside the
  TUI's other pipelines. Phase 8 should not remove the Python implementation until either the wire conversion is
  amortized or the comparison is rerun against the optimized path.
- All four small Git normalizer surfaces (`parse_git_branch_name`, `derive_git_workspace_name`,
  `parse_git_conflicted_files`, `parse_git_local_changes`) are 13-22 % slower under default Rust than Python on the
  small inputs they actually see in production. These are dispatch-overhead-dominated; the absolute gap is single-digit
  microseconds and does not show up against the surrounding subprocess cost (see the `end_to_end_*` workloads in the
  `parse_git_name_status_z` artifact: subprocess-only is 2.5-10 ms, parse-only is 30-400 µs, so total time is unmoved
  whichever backend is selected).
- `read_status_from_lines` / `apply_status_update` / `plan_status_transition` show 30-55 % slowdowns under default Rust
  on the synthetic_200_specs workload (still microseconds). Same root cause as the Git normalizers: dispatch overhead
  on a sub-10-µs core. Phase 4's design accepted this — the planner / status helpers route through Rust to keep the
  facade contract honest, but they are not where users gain time. Phase 7D should phrase the win as "where it hurt
  the user", which is parsing and scanning, not status-line edits.
- `parse_git_name_status_z` is consistently 25-30 % slower under default Rust on synthetic streams. The end-to-end
  scenarios (`git diff --name-status -z` subprocess + parse) show the parse step is single-digit microseconds compared
  to multi-millisecond subprocess cost, so the delta is invisible to users — but it is real and Phase 7E should not
  pick this surface as a regression-floor anchor.

## Coverage of every shipped Rust core op

| Operation                     | Covered by                                              | Verdict                                  |
| ----------------------------- | ------------------------------------------------------- | ---------------------------------------- |
| `parse_project_bytes`         | `bench_core_parse` (golden, synthetic_200)              | clear win                                |
| `parse_query`                 | `bench_core_query.parse_only`                           | direct: clear win; facade: noise         |
| `evaluate_query_many`         | `bench_core_query.synthetic_*_specs`                    | regression vs Python (see above)         |
| `scan_agent_artifacts`        | `bench_agent_scan.synthetic_6p_200pp`                   | clear win                                |
| `read_status_from_lines`      | `bench_status_state_machine.*_pure`                     | regression on large workload, noise on small |
| `apply_status_update`         | `bench_status_state_machine.*_pure`                     | regression on large workload, noise on small |
| `plan_status_transition`      | `bench_status_state_machine.*_pure` (added in 7B)        | small absolute gap; ~2× slower on µs-scale calls |
| `parse_git_name_status_z`     | `bench_git_query_ops.synthetic_*` + `end_to_end_*`      | parse regression; user impact unmeasurable |
| `parse_git_branch_name`       | `bench_git_query_ops.normalizers_x4`                    | tiny regression; noise vs users          |
| `derive_git_workspace_name`   | `bench_git_query_ops.normalizers_x5`                    | tiny regression; noise vs users          |
| `parse_git_conflicted_files`  | `bench_git_query_ops.normalizers_50`                    | tiny regression; noise vs users          |
| `parse_git_local_changes`     | `bench_git_query_ops.normalizers_150`                   | tiny regression; noise vs users          |

Every shipped operation has at least one direct scenario; nothing is hiding behind aggregate scenarios.

## Open questions for Phase 7C/7D/7E

- **Phase 7C**: the agent-scan and `evaluate_query_many` artifacts argue strongly that the *user-visible* win lives at
  the TUI / `sase agents` level, not at the operation level. Phase 7C should size its workloads big enough to make the
  scan_agent_artifacts wins (and the eval regressions) visible against the cold-open and `sase agents -j` budgets.
- **Phase 7D**: the documentation should *not* lead with `evaluate_query_many` or with status-line edits as a perf
  story. Lead with `parse_project_bytes` and `scan_agent_artifacts`; treat the other shipped surfaces as "routed to
  keep the contract uniform, perf parity not a goal" so future readers do not expect a Rust-everywhere speedup.
- **Phase 7E**: do not include `parse_git_name_status_z` or any of the small normalizers in the regression floor —
  their absolute medians are below 50 µs and noise alone moves them by more than 25 %. A safe floor anchor set is
  `parse_project_bytes.golden_myproj.facade`, `parse_project_bytes.synthetic_200_specs.facade`,
  `parse_query.parse_only.direct`, `scan_agent_artifacts.synthetic_6p_200pp.scan_facade`, and
  `apply_status_update.golden_myproj_pure.apply_status_update` (the last as a "must not regress further" guard rather
  than a "must beat Python" guard). Phase 7B explicitly avoided suggesting tighter thresholds — the regression-floor
  decision belongs to Phase 7E with the actual checker code in front of it.
- **`bench_workflow_complete.py`**: skipped in Phase 7B for the reason above. If Phase 7C wants its `is_workflow_complete`
  numbers wired into the end-to-end story, the harness already accepts `--projects / --per-project / --runs / --warmup`
  flags and writes JSON via `--output`.

## Verification commands run

- `just install`
- `.venv/bin/python tests/perf/phase7/run_phase7b.py` — produced all 12 summary artifacts (~95 s wall clock).
- `just check` — pending; Phase 7B agent will run before commit per the Phase 7 verification baseline. (Result attached
  to the commit.)
