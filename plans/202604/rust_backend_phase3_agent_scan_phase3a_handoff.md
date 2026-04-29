---
create_time: 2026-04-29
status: done
bead_id: sase-18.1
---

# Rust Backend Phase 3A — Python Contract, Corpus, and Baseline Measurements

Closes the Phase 3A subphase of `../sase_100/plans/202604/rust_backend_phase3_agent_scan.md`. This
document records what landed in `sase_100` for Phase 3A, the wire contract Phase 3B must mirror in
`../sase-core`, the golden corpus shape, and the baseline benchmark numbers Phase 3D–3H will need to
beat to justify routing artifact-scan call sites through the Rust backend.

## What landed

| Area              | Module / file                                                | Notes                                                                                  |
| ----------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| Wire contract     | `src/sase/core/agent_scan_wire.py`                           | `AGENT_SCAN_WIRE_SCHEMA_VERSION = 1`; dataclasses listed below.                        |
| Python facade     | `src/sase/core/agent_scan_facade.py`                         | `scan_agent_artifacts()` / `scan_agent_artifacts_python()` via `sase.core.backend`.    |
| Golden corpus     | `tests/agent_scan_golden/fixture_builder.py`                 | Programmatic synthetic tree covering the cases listed in Phase 3A.                     |
| Parity tests      | `tests/test_core_agent_scan.py`                              | Pins wire shape, ordering, error counters, options behavior.                           |
| Baseline bench    | `tests/perf/bench_agent_scan.py` + `just bench-agent-scan`   | Times the new facade alongside the existing direct loaders / TUI loaders.              |
| Docs              | `docs/rust_backend.md`                                       | New facade modules + `bench-agent-scan` listed; roadmap entry for Phase 3A.            |

No Rust code was added in Phase 3A — that is Phase 3B's job in `../sase-core`.

## Wire contract Phase 3B must reproduce

`AgentArtifactScanWire` is a top-level snapshot record with:

- `schema_version: int` — currently `1`. Bump on incompatible shape changes.
- `projects_root: str` — the absolute root that was scanned.
- `options: AgentArtifactScanOptionsWire` — the options used for the scan.
- `stats: AgentArtifactScanStatsWire` — diagnostic counters for the scan.
- `records: list[AgentArtifactRecordWire]` — sorted by
  `(project_name, workflow_dir_name, timestamp)`.

`AgentArtifactScanOptionsWire` carries the four knobs Python supplies:

- `include_prompt_step_markers: bool` (default `True`)
- `include_raw_prompt_snippets: bool` (default `True`)
- `max_prompt_snippet_bytes: int` (default `200`)
- `only_workflow_dirs: tuple[str, ...]` (default `()` = all supported families)

`AgentArtifactScanStatsWire` carries the soft-error counters Phase 3 must surface so a single bad
artifact never breaks a scan:

- `projects_visited`, `artifact_dirs_visited`
- `marker_files_parsed`, `prompt_step_markers_parsed`
- `json_decode_errors`, `os_errors`

Each `AgentArtifactRecordWire` carries the path identity (`project_name`, `project_dir`,
`project_file`, `workflow_dir_name`, `artifact_dir`, `timestamp`) plus optional projections of every
supported marker:

- `agent_meta: AgentMetaWire | None`
- `done: DoneMarkerWire | None`
- `running: RunningMarkerWire | None`
- `waiting: WaitingMarkerWire | None`
- `workflow_state: WorkflowStateWire | None`
- `plan_path: PlanPathMarkerWire | None`
- `prompt_steps: list[PromptStepMarkerWire]` (sorted by file name)
- `raw_prompt_snippet: str | None`
- `has_done_marker: bool` — set even when `done.json` failed to decode, mirroring
  `done_path.exists()` checks in current Python loaders.

The supported workflow directory families live in `agent_scan_wire.py` as module constants so the
Rust scanner can use the same lists:

- `DONE_WORKFLOW_DIR_NAMES = ("ace-run", "run", "fix-hook", "crs", "summarize-hook")`
- `DONE_WORKFLOW_DIR_PREFIXES = ("mentor-",)`
- `WORKFLOW_STATE_DIR_NAMES = ("ace-run", "run")`
- `WORKFLOW_STATE_DIR_PREFIXES = ("workflow-",)`

## Phase 3A non-goals (intentional carry-overs)

These were called out in the Phase 3 plan's "Phase 3 Non-Goals" / "Phase Split" sections and are
NOT addressed in 3A:

- No process-liveness checks. Phase 3 keeps `is_process_running()` and `/proc` guards in Python.
  The wire surfaces `pid` so future phases can move liveness if/when warranted.
- No RUNNING-field / workspace-claim parsing. `sase.running_field` stays Python-only in Phase 3.
- No mutation paths. `claim_agent_name()`, `release_workspace()`, dismissed-bundle writes stay
  Python-only.
- No persistent cache. The facade re-walks the tree on every call. Phase 3G decides whether a
  streaming or cached API is justified.
- No Rust dispatch yet. `SASE_CORE_BACKEND=rust scan_agent_artifacts(...)` currently raises
  `RustBackendUnavailableError` (the standard "Rust backend requested but not registered"
  behavior). Phase 3C registers the Rust impl.

## Golden corpus shape

`tests/agent_scan_golden/fixture_builder.py::build_fixture_tree(root)` materializes a
hermetic synthetic tree under `root` covering the cases the Phase 3A plan called for:

| Timestamp        | Project   | Workflow dir              | What it covers                                                |
| ---------------- | --------- | ------------------------- | ------------------------------------------------------------- |
| `20260427100000` | `home`    | `ace-run`                 | home-mode running marker (`running.json` + `agent_meta.json`) |
| `20260427110000` | `myproj`  | `ace-run`                 | running ace-run agent with plan + `wait_for` list             |
| `20260427120000` | `myproj`  | `ace-run`                 | done ace-run agent (`outcome=completed`)                      |
| `20260427130000` | `myproj`  | `ace-run`                 | failed ace-run agent (`outcome=failed`, error + traceback)    |
| `20260427140000` | `myproj`  | `ace-run`                 | retried parent (`retried_as_timestamp`)                       |
| `20260427140500` | `myproj`  | `ace-run`                 | retried child (`retry_of_timestamp`, `retry_attempt=1`)       |
| `20260427150000` | `myproj`  | `workflow-three_phase`    | workflow root (`workflow_state.json`) + 3 prompt-step markers |
| `20260427160000` | `myproj`  | `mentor-bryan`            | mentor-prefix workflow folder with `done.json` only           |
| `20260427170000` | `myproj`  | `ace-run`                 | waiting marker (intentionally malformed JSON, soft-skipped)   |
| `20260427180000` | `myproj`  | `ace-run`                 | malformed `agent_meta.json` (soft-skipped + counted)          |

Two intentional decode errors are written into the tree (the malformed `waiting.json` and the
malformed `agent_meta.json`). The parity tests pin
`stats.json_decode_errors == 2`. Adding a new fixture branch that introduces another soft error
must update `EXPECTED_DECODE_ERRORS` in `fixture_builder.py` so the change is reviewed.

## Baseline benchmark

`tests/perf/bench_agent_scan.py` builds a synthetic tree and times every Phase 3A scenario.
Marked `slow` so it does not run in `just test`.

```bash
just bench-agent-scan
just bench-agent-scan --projects 4 --per-project 40 --runs 5 --warmup 2
```

A representative single-machine run (4 projects × 40 artifact directories, ~25% with workflow
state, runs=5 warmup=2) on the development host that recorded this handoff:

```
# synthetic_4p_40pp
  scenario                                 min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------------------------
  find_named_agent                        169.621      170.876    187.429    187.429
  is_workflow_complete                      0.131        0.137      0.156      0.156
  list_running_agents                       0.127        0.129      0.133      0.133
  list_all_agents                           0.139        0.141      0.146      0.146
  tui_artifact_load                         0.180        0.183      0.203      0.203
  scan_python_facade                       16.950       17.023     17.069     17.069
  scan_python_facade_no_prompt_steps       12.979       13.143     14.469     14.469
```

Read these as **shape, not target**:

- `find_named_agent` is the dominant single-call cost in this synthetic and matches the production
  observation that motivated Phase 3 — it walks every project's `ace-run` tree without an mtime
  cache.
- `scan_python_facade` is intentionally an order-of-magnitude wider in surface area than any
  individual loader: it parses `agent_meta`, `done`, `running`, `waiting`, `workflow_state`,
  `plan_path`, `prompt_step_*`, and a `raw_xprompt.md` snippet for **every** artifact directory.
  The Phase 3D/3E/3F integrations expect to amortize one snapshot across many call sites, so this
  is a single-cost number that replaces the **sum** of the others.
- The other scenario timings collapse to ~0.1ms because the synthetic PIDs are not alive and the
  loaders short-circuit; this is a worst-case measurement of the FS walk minus liveness work, and
  is mainly useful as a regression guard. Production timings will look very different.
- The `scan_python_facade_no_prompt_steps` row exists to show the cost contribution of the
  per-directory `glob("prompt_step_*.json")`. Phase 3B can use the gap as a hint for where Rust
  parallelism can buy the most back.

`just bench-agent-scan --include-home` adds a real `~/.sase/projects` workload when present.
This is intentionally not run automatically.

## Verification performed for Phase 3A

```bash
just install
.venv/bin/pytest tests/test_core_agent_scan.py        # 24 tests pass
just bench-agent-scan --projects 4 --per-project 40   # baseline above
just check
```

`just check` results land in the commit message; this handoff is finalized when both the parity
tests and `just check` are green.

## What Phase 3B should look at first

- Mirror every wire dataclass in Rust under `../sase-core/crates/sase_core/src/agent_scan/`.
  Use `serde::{Serialize, Deserialize}, Debug, Clone, PartialEq` so dual-run comparisons in
  Phase 3C have something to lean on.
- Walk only the workflow directory families listed above (constants in `agent_scan_wire.py`).
  Anything else under `projects/<p>/artifacts/` must be silently ignored.
- Treat malformed marker JSON and unreadable directories as soft errors. Increment the typed
  counter on `AgentArtifactScanStatsWire` rather than raising. The Phase 3A golden corpus
  exercises the two decode-error paths the wire pins.
- Sort returned records by `(project_name, workflow_dir_name, timestamp)` before serializing.
  Internal parallelism is fine; deterministic output is required for golden parity.
- Do not read global config from Rust. Python supplies `projects_root` explicitly (the wire
  records the absolute path it was given so a Rust port can verify the contract).

## Open questions handed to Phase 3B+

1. Should `prompt_step_*.json` enumeration use a globber or a directory scan in Rust? The Phase 3A
   facade uses `Path.glob("prompt_step_*.json")`. A `walkdir`-based filter that processes each
   directory's entries once may be cheaper.
2. Should Rust skip parsing markers when `only_workflow_dirs` excludes the directory family
   entirely? The Python implementation already short-circuits before iterating timestamp dirs;
   Rust should match.
3. The wire currently exposes `step_output` as an arbitrary JSON object. Phase 3F will tell us
   whether this is too loose. If the TUI only consumes `meta_*` keys plus `plan_path`, `diff_path`,
   `response_path`, the wire could tighten the schema in a v2 bump.
