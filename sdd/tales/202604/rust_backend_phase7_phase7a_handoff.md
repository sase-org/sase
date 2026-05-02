# Phase 7A Handoff: Measurement Contract And Artifact Schema

Bead: `sase-1e.1`. Plan: `plans/202604/rust_backend_phase7.md`. Phase 7A locks the artifact contract Phase 7B/7C will
produce against and Phase 7D/7E will read.

## What landed

- `tests/perf/phase7/` — new helper package.
  - `metadata.py` — `BackendChoice` (enum: `default_python` / `default_rust` / `explicit_python` / `explicit_rust` /
    `summary`), `Phase7Metadata` dataclass, `build_metadata()` (git SHA + dirty flag, ISO-8601 UTC timestamp, Python /
    platform / processor, `sase_core_rs` import path + version, run/warmup, surface, workload), and `artifact_path()`
    for the canonical filename.
  - `summary.py` — `scenario_median()` (accepts `median_s` / `median_ms` / `median_us` / `median_ns`),
    `compute_speedup()` returning a `ScenarioComparison` with `ratio`, `speedup`, and `percent_delta`, and
    `summarize_report()` to pivot a per-workload pair of scenario maps without per-benchmark glue code.
  - `test_phase7_helpers.py` — 20 unit tests including a smoke pivot against the committed Phase 4A
    `bench_status_state_machine_phase4a.json` so the helper proves it can roll up an existing benchmark JSON shape with
    no changes to that benchmark. Runs in the default (fast) test suite.
- `plans/202604/perf_artifacts/README.md` — locks naming convention, the required envelope, sanitisation rules for
  end-to-end Phase 7C artifacts, and lists pre-existing artifacts that predate the convention.
- `Justfile` — `just phase7-perf-check` wraps the helper smoke. Phase 7E will replace this body with the real
  regression-floor invocation once the stable subset is chosen; the target name is reserved now so the plan's exit
  command does not have to rename later.

Out of scope for Phase 7A and explicitly not done:

- No changes to existing benchmark harnesses (`bench_core_parse.py`, `bench_core_query.py`, `bench_agent_scan.py`,
  `bench_status_state_machine.py`, `bench_tui_trace.py`). Phase 7B is the agent that adopts the helper.
- No new benchmark JSON files. Phase 7B/7C own the artifact production.
- No CI integration. Phase 7E owns the regression floor.

## Naming convention (locked)

```
plans/202604/perf_artifacts/rust_backend_phase7_<surface>_<backend_or_summary>.json
```

`<surface>` values are intended to be stable across phases and machines so Phase 7D can pivot. Use:

| Phase 7B core operations    | Phase 7C end-to-end surfaces |
| --------------------------- | ---------------------------- |
| `parse_project_bytes`       | `sase_ace_cold_open`         |
| `parse_query`               | `sase_agents_status_listing` |
| `evaluate_query_many`       | `sase_run_startup`           |
| `scan_agent_artifacts`      |                              |
| `read_status_from_lines`    |                              |
| `apply_status_update`       |                              |
| `plan_status_transition`    |                              |
| `parse_git_name_status_z`   |                              |
| `parse_git_branch_name`     |                              |
| `derive_git_workspace_name` |                              |
| `parse_git_conflicted_files`|                              |
| `parse_git_local_changes`   |                              |

`<backend_or_summary>` is one of the `BackendChoice` values in `tests/perf/phase7/metadata.py`. Hand-formatted strings
are accepted but `tests/perf/phase7.artifact_path()` is the canonical entry point.

## Expected Phase 7B artifacts

Phase 7B should at minimum produce one default-Rust artifact and one explicit-Python artifact for every shipped Rust
operation (or document why a coarser aggregate is the right answer for that operation). The expected file list:

- `rust_backend_phase7_parse_project_bytes_default_rust.json`
- `rust_backend_phase7_parse_project_bytes_explicit_python.json`
- `rust_backend_phase7_parse_query_default_rust.json`
- `rust_backend_phase7_parse_query_explicit_python.json`
- `rust_backend_phase7_evaluate_query_many_default_rust.json`
- `rust_backend_phase7_evaluate_query_many_explicit_python.json`
- `rust_backend_phase7_scan_agent_artifacts_default_rust.json`
- `rust_backend_phase7_scan_agent_artifacts_explicit_python.json`
- `rust_backend_phase7_read_status_from_lines_default_rust.json`
- `rust_backend_phase7_read_status_from_lines_explicit_python.json`
- `rust_backend_phase7_apply_status_update_default_rust.json`
- `rust_backend_phase7_apply_status_update_explicit_python.json`
- `rust_backend_phase7_plan_status_transition_default_rust.json`
- `rust_backend_phase7_plan_status_transition_explicit_python.json`
- `rust_backend_phase7_parse_git_name_status_z_default_rust.json`
- `rust_backend_phase7_parse_git_name_status_z_explicit_python.json`
- `rust_backend_phase7_parse_git_branch_name_default_rust.json`
- `rust_backend_phase7_parse_git_branch_name_explicit_python.json`
- `rust_backend_phase7_derive_git_workspace_name_default_rust.json`
- `rust_backend_phase7_derive_git_workspace_name_explicit_python.json`
- `rust_backend_phase7_parse_git_conflicted_files_default_rust.json`
- `rust_backend_phase7_parse_git_conflicted_files_explicit_python.json`
- `rust_backend_phase7_parse_git_local_changes_default_rust.json`
- `rust_backend_phase7_parse_git_local_changes_explicit_python.json`

For benchmarks whose existing harnesses already produce one report per process containing both backends (e.g.
`bench_status_state_machine.py`), Phase 7B may keep that shape and instead emit per-surface summary artifacts named
with the `summary` tag (e.g. `rust_backend_phase7_apply_status_update_summary.json`). Use
`tests/perf/phase7.summarize_report()` to derive those summaries; do not roll a private parser.

## Expected Phase 7C artifacts

- `rust_backend_phase7_sase_ace_cold_open_default_rust.json` and `_explicit_python.json`
- `rust_backend_phase7_sase_agents_status_listing_default_rust.json` and `_explicit_python.json`
- `rust_backend_phase7_sase_run_startup_default_rust.json` and `_explicit_python.json`

Where the synthetic vs home-tree distinction matters (e.g. `sase_agents_status`), Phase 7C should put the workload
distinguisher inside the `workload` metadata field rather than inventing a new surface tag. That keeps the per-surface
artifact count low and lets Phase 7D's tables stay flat.

## How Phase 7B/7C should adopt the helper

1. Inside the existing `run_bench()` function, build the envelope:

   ```python
   from tests.perf.phase7 import BackendChoice, build_metadata, artifact_path

   metadata = build_metadata(
       tool="bench_core_parse",
       surface="parse_project_bytes",
       workload=workload_label,
       backend=BackendChoice.DEFAULT_RUST,
       runs=runs,
       warmup=warmup,
   )
   report = {"metadata": metadata.as_dict(), "workloads": [...]}
   ```

2. Pick the destination via `artifact_path(surface=..., backend_or_summary=BackendChoice.DEFAULT_RUST)`.
3. Keep the existing per-scenario summary shape; the helper accepts `median_ms` and `median_us` directly.

The helper deliberately does not run subprocesses for git or the Rust extension probe in a way that can fail the
benchmark — every probe degrades to a `None` field instead of raising.

## Verification commands run

- `just install`
- `just phase7-perf-check` — 20 passed.
- `just check` — full repo check (fmt, lint, mypy, pyscripts, pyvision, fast tests). See commit message for the exact
  shell.

## Open questions for later phases

- Phase 7B should record whether `bench_workflow_complete.py` (referenced in the plan) already exists or needs to be
  added. It was not present in the repo at the time of this handoff and so was not exercised by the helper smoke. If
  Phase 7B chooses to skip it, document the decision rather than silently dropping the listed workload.
- Phase 7E should decide whether `phase7-perf-check` keeps wrapping the helper smoke or shells into the regression
  checker directly. Either way, the handoff document for 7E should cover the rename if the body changes meaningfully.
