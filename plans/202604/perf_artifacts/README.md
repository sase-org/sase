# Phase 7 Performance Artifacts

This directory holds the JSON evidence for the Rust backend migration's Phase 7 measurement pass
(`plans/202604/rust_backend_phase7.md`). Phase 7A locked the artifact contract here so every later phase produces
comparable numbers.

## Naming convention

```
plans/202604/perf_artifacts/rust_backend_phase7_<surface>_<backend_or_summary>.json
```

- `<surface>` — the operation or user-visible surface being measured. Use the labels listed below so Phase 7D and 7E can
  pivot artifacts without special casing. Examples:
  - core operations: `parse_project_bytes`, `parse_query`, `evaluate_query_many`, `scan_agent_artifacts`,
    `read_status_from_lines`, `apply_status_update`, `plan_status_transition`, `parse_git_name_status_z`,
    `parse_git_branch_name`, `derive_git_workspace_name`, `parse_git_conflicted_files`, `parse_git_local_changes`;
  - end-to-end surfaces: `sase_ace_cold_open`, `sase_agents_status_listing`, `sase_run_startup`.
- `<backend_or_summary>` — one of the `BackendChoice` values defined in `tests/perf/phase7/metadata.py`:
  - `default_python` — no `SASE_CORE_BACKEND` override, sase ships with Python default.
  - `default_rust` — no override, sase ships with Rust default. Phase 6 flipped the default; Phase 7 measures the
    user-visible result.
  - `explicit_python` / `explicit_rust` — env var pinned (`SASE_CORE_BACKEND=python|rust`).
  - `summary` — Phase 7D / Phase 7E rollup that compares two artifacts. Custom summary tags are allowed (e.g.
    `ratio_summary`) but should still be lowercase and `_`-joined.

`tests/perf/phase7.artifact_path()` is the canonical way to spell these names; benchmarks and Justfile targets should
call it instead of hand-formatting strings.

## Required envelope

Every artifact embeds the common metadata returned by `tests/perf/phase7.build_metadata()` so a Phase 7D dashboard or
the Phase 7E regression checker can pivot across surfaces and machines. The envelope is JSON-serialisable and looks
like:

```json
{
  "phase": "7",
  "tool": "bench_core_parse",
  "surface": "parse_project_bytes",
  "workload": "synthetic_1000_specs",
  "backend": "default_rust",
  "runs": 20,
  "warmup": 3,
  "timestamp": "2026-04-29T15:42:11Z",
  "git_sha": "ab7a622c0f00",
  "git_dirty": false,
  "python": "3.14.3",
  "system": "Linux",
  "machine": "x86_64",
  "processor": "x86_64",
  "rust_available": true,
  "rust_module_path": "/.../sase_core_rs.cpython-314-x86_64-linux-gnu.so",
  "rust_module_version": "0.1.0"
}
```

`extra` is included only when the harness supplies surface-specific keys (e.g. terminal size for a TUI cold-open
artifact, projects-root for an agent-scan artifact). Keep `extra` JSON-serialisable; do not embed Python objects.

## Per-surface body

The metadata envelope sits next to a `workloads` array (or whatever shape the surface's existing benchmark already
emits). Phase 7B and 7C should keep their existing scenario shapes — Phase 7A explicitly chose to adapt rather than
rewrite them — provided each scenario summary still exposes a `count` plus one of `median_s`, `median_ms`, `median_us`,
or `median_ns`. `tests/perf/phase7.summarize_report()` reads any of those without conversion.

## Sanitisation

End-to-end artifacts (Phase 7C) may capture real `$HOME` paths, project file names, or prompt text. Sanitise before
committing:

- Replace home directories with `~` or a stable placeholder.
- Drop or hash project paths users would not want public.
- Never include prompt bodies, chat transcripts, or LLM responses.

If a sanitisation step would lose signal, write the artifact under a `local_only/` subdirectory (gitignored) and link
to it from the surface's handoff instead of committing the raw file.

## Existing artifacts

- `bench_status_state_machine_phase4a.json` — Phase 4A baseline, kept as input for the Phase 7A helper smoke test.
- `bench_agent_scan_phase4a_recap.json` — Phase 4A recap, same purpose.

These predate the Phase 7A naming convention and stay under their original names. New artifacts produced by Phase 7B
and 7C must follow the convention above.

## Runtime-generated (gitignored)

- `rust_backend_phase7_floor_check.json` — Phase 7E regression-floor report. Regenerated every time
  `just phase7-perf-check` runs (locally or in CI) and gitignored so per-machine measurements never get committed.
  CI uploads this file as the `phase7-perf-floor-report` artifact so a regression can be inspected post-hoc.
