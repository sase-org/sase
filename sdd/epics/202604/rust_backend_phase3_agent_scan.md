---
create_time: 2026-04-29 09:18:29
status: done
bead_id: sase-18
prompt: sdd/prompts/202604/rust_backend_phase3_agent_scan.md
---
# Rust Backend Migration Phase 3: Agent / Artifact Filesystem Scan

## Context

`sdd/research/202604/rust_backend_migration.md` defines Phase 3 as the Rust port of the agent/artifact filesystem scan. This
phase should target work users can feel: listing, resolving, and refreshing agents currently walks
`~/.sase/projects/*/artifacts/...` and parses many small JSON files from Python.

Phases 0, 1, and 2 are complete in this checkout:

- Phase 0 created the Python `sase.core` facade, backend dispatch, dual-run logging, and wire contracts.
- Phase 1 wired the optional sibling Rust extension `../sase-core` into `parse_project_bytes()`.
- Phase 2 added query facade/batch APIs and Rust query bindings, but the rollout decision kept Rust query evaluation
  opt-in because Python-to-wire conversion dominated runtime.

Phase 3 has a better performance profile than Phase 2 because Rust can own the expensive part directly: directory
walking and JSON parsing from filesystem bytes. The design should avoid converting existing Python `Agent` objects into
Rust and back. Instead, Rust should scan the artifact tree from a root path and return a compact snapshot of
already-read artifact metadata for Python to adapt into current models.

Current Python scan surfaces to account for:

- `src/sase/agent/names/_lookup.py`
  - `find_named_agent()`
  - `is_workflow_complete()`
- `src/sase/agent/running.py`
  - `list_running_agents()`
  - `list_all_agents()`
- `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`
  - `get_all_project_files()`
  - `load_done_agents()`
  - `load_running_home_agents()`
  - `enrich_agent_from_meta()`
- `src/sase/ace/tui/models/_loaders/_workflow_loaders.py`
  - workflow timestamp-dir discovery
  - `load_workflow_states()`
  - `load_workflow_agents()`
  - `load_workflow_agent_steps()`

The Python JSON cache and thread pool already reduce repeated reads, so the phase must be measurement-driven. The first
Rust rollout should be a snapshot API, not a streaming API. Streaming can follow once snapshot parity and end-to-end
benchmarks prove that returning one large snapshot is still too slow for first-frame rendering.

## Target Shape

Add a new operation family behind `sase.core`:

```text
scan_agent_artifacts(projects_root, options) -> AgentArtifactScanWire
```

`projects_root` should be passed explicitly by Python, normally `Path.home() / ".sase" / "projects"`, so tests and
future server/mobile shells can control the root without Rust reading global config.

The Rust side should:

- Walk project artifact trees with `walkdir` and parallelize JSON parsing with `rayon`.
- Use `serde_json` first for simplicity. Move to `simd-json` or `sonic-rs` only after a benchmark shows JSON parsing,
  not directory metadata or FFI conversion, is the bottleneck.
- Return owned strings, booleans, integers, arrays, and maps only.
- Release the GIL in PyO3 around the filesystem scan.
- Ignore malformed or unreadable JSON the same way current Python loaders do, while counting errors in the scan metadata
  so diagnostics are possible.

The Python side should:

- Keep existing `Agent`, `WorkflowEntry`, and `RunningAgentInfo` dataclasses as the public model.
- Keep existing process-liveness checks in Python at first. Rust may return PID and `stopped_at`, but Python should keep
  using `sase.ace.hooks.processes.is_process_running()` and `/proc` command-line guards until parity is proven.
- Keep workspace-claim parsing from `.gp` files in Python. The Rust scan can return project file paths and artifact
  timestamps, but RUNNING-field semantics are already tied to existing ChangeSpec file mutation logic.
- Preserve the Python backend as default until the scan clears the research gate: first usable batch under 100 ms or
  total scan at least 2x faster end to end.

## Phase Split for Distinct Agent Instances

Each subphase below is intended for a separate `claude` / `gemini` / `codex` agent instance. Later agents should read
this full plan and the handoff notes from earlier subphases, but should only own their listed write scope.

### Phase 3A: Python Contract, Corpus, and Baseline Measurements

Goal: define the artifact-scan wire contract and establish a Python baseline before touching Rust behavior.

Write scope:

- `sase_100/src/sase/core/agent_scan_wire.py` or equivalent focused module.
- `sase_100/src/sase/core/agent_scan_facade.py`.
- `sase_100/tests/` fixtures and golden/parity tests.
- `sase_100/tests/perf/bench_agent_scan.py`.
- `sase_100/docs/rust_backend.md` or a short plan handoff note if needed.

Work:

- Add wire dataclasses for a snapshot-level contract. Suggested records:
  - `AgentArtifactScanOptionsWire`
  - `AgentArtifactScanStatsWire`
  - `AgentArtifactRecordWire`
  - `DoneMarkerWire`
  - `AgentMetaWire`
  - `RunningMarkerWire`
  - `WaitingMarkerWire`
  - `WorkflowStateWire`
  - `PromptStepMarkerWire`
  - `PlanPathMarkerWire`
  - `AgentArtifactScanWire`
- Keep the contract compact. Do not expose the full arbitrary JSON trees unless a downstream loader truly needs them.
  Start with fields currently used by name resolution, running/done CLI listing, workflow display, retry lineage,
  wait/plan status enrichment, prompt-step meta fields, response/diff/output paths, model/provider/name fields, and
  error/traceback fields.
- Include enough path identity to rebuild current behavior:
  - `project_name`
  - `project_dir`
  - `project_file`
  - `workflow_dir_name`
  - `artifact_dir`
  - `timestamp`
- Add a pure-Python scanner implementation behind the facade that produces the same wire snapshot from fixtures and real
  roots. It can call existing cached JSON helpers internally, but its public shape must be the new wire shape.
- Add golden fixtures under `tests/agent_scan_golden/` that cover:
  - running `ace-run` agent with `agent_meta.json`
  - done `ace-run` agent with `done.json`
  - failed and retried done agents
  - home-mode `running.json`
  - workflow root with `workflow_state.json`
  - prompt step markers with `meta_*`, path outputs, hidden/pre-prompt flags
  - waiting agents with `waiting.json`
  - malformed JSON files that should be skipped/counted
  - missing optional files
- Add a benchmark that reports at least:
  - current Python direct named-agent scan
  - current Python direct workflow-complete scan
  - current Python `list_all_agents()`
  - current Python TUI loader artifact/workflow portions if practical
  - new Python facade snapshot scan

Exit criteria:

- Golden tests pin the wire snapshot shape and error-count behavior.
- Baseline benchmark output is documented in the phase handoff.
- No Rust code is required for this phase.
- `just check` passes in `sase_100`.

### Phase 3B: Pure-Rust Snapshot Scanner in `../sase-core`

Goal: implement the filesystem snapshot in the pure Rust crate, without Python integration beyond Rust tests.

Write scope:

- `../sase-core/crates/sase_core/src/agent_scan/` or equivalent.
- `../sase-core/crates/sase_core/src/lib.rs`.
- `../sase-core/crates/sase_core/tests/`.
- `../sase-core/README.md` if new commands/options need documenting.

Work:

- Mirror the Phase 3A wire records in Rust with `serde::{Serialize, Deserialize}`, `Debug`, `Clone`, and `PartialEq`
  where useful.
- Implement:
  - `scan_agent_artifacts(projects_root: &Path, options: AgentArtifactScanOptionsWire) -> AgentArtifactScanWire`
- Traverse these artifact families:
  - `projects/*/artifacts/ace-run/*`
  - `projects/*/artifacts/run/*`
  - `projects/*/artifacts/workflow-*/*`
  - current done-agent workflow directories: `fix-hook`, `crs`, `summarize-hook`, and `mentor-*`
- Parse only known marker files:
  - `agent_meta.json`
  - `done.json`
  - `running.json`
  - `waiting.json`
  - `workflow_state.json`
  - `plan_path.json`
  - `prompt_step_*.json`
- Treat unreadable directories and malformed marker files as soft errors. Skip the bad file/record when current Python
  behavior skips it, and increment a typed counter in `AgentArtifactScanStatsWire`.
- Keep scan ordering deterministic in returned data. Parallel parsing is fine internally, but sort by project, workflow
  dir, timestamp, and marker name before serializing.
- Add Rust tests using fixture trees equivalent to the Phase 3A Python fixtures.

Exit criteria:

- `cargo fmt --all -- --check` passes in `../sase-core`.
- `cargo clippy --workspace --all-targets -- -D warnings` passes.
- `cargo test --workspace` passes.
- Rust snapshot JSON matches the fixture expectation from Phase 3A, modulo explicitly documented ordering or stat
  fields.

### Phase 3C: PyO3 Binding and Facade Dual-Run

Goal: expose the Rust scanner through `sase_core_rs` and route the new Python scan facade through backend dispatch.

Write scope:

- `../sase-core/crates/sase_core_py/src/lib.rs`.
- `sase_100/src/sase/core/agent_scan_facade.py`.
- `sase_100/src/sase/core/agent_scan_wire.py` if adapter helpers need refinement.
- `sase_100/tests/test_core_facade.py` or focused agent-scan facade tests.
- `sase_100/docs/rust_backend.md`.

Work:

- Add PyO3 function:
  - `scan_agent_artifacts(projects_root: str, options: dict | None = None) -> dict`
- Release the GIL while Rust walks and parses files.
- Convert Rust output to plain Python dict/list primitives, matching the Phase 3A wire dataclasses exactly.
- Register a Rust implementation in `sase.core.agent_scan_facade` only when `sase_core_rs` exposes
  `scan_agent_artifacts`.
- Add dual-run support using operation names such as `scan_agent_artifacts`.
- Use a custom comparator if necessary to ignore timing counters or ordering fields that are not semantic.
- Add tests for:
  - missing Rust extension leaves Python backend working
  - fake Rust module is selected under `SASE_CORE_BACKEND=rust`
  - dual-run returns Python output and writes mismatch records
  - real Rust extension parity when installed, using `pytest.importorskip("sase_core_rs")`

Exit criteria:

- `SASE_CORE_BACKEND=python` behavior is unchanged.
- `SASE_CORE_BACKEND=rust` can scan fixture roots when the extension is installed.
- `SASE_CORE_DUAL_RUN=1` logs scan comparison records and returns Python results.
- Focused Python tests pass; `just check` passes if this repo changed.

### Phase 3D: Name Resolution on the Scan Snapshot

Goal: move the highest-frequency name lookup operations onto the scan facade while keeping Python liveness semantics.

Write scope:

- `sase_100/src/sase/agent/names/_lookup.py`.
- Focused helpers in `sase_100/src/sase/agent/names/` if needed.
- `sase_100/tests/test_agent_names.py`.
- `sase_100/tests/test_agent_names_workflow.py`.
- Related tests for dismissed bundles and agent reference resolution.

Work:

- Rework `find_named_agent()` to consume `scan_agent_artifacts()` records for `ace-run` artifact metadata instead of
  directly walking every project directory.
- Preserve existing behavior exactly:
  - running exact-name matches return immediately only when Python liveness checks pass
  - running agents beat done agents unless `only_done=True`
  - exact `name` beats `workflow_name`
  - workflow-name done matches prefer newest timestamp
  - parent workflow children are not returned as running roots
  - dismissed-prefixed artifacts without `done.json` count as historical completed agents
  - dismissed bundle fallback remains Python-only and still runs when no artifact match exists
- Rework `is_workflow_complete()` to consume the same snapshot and preserve the root/child/dead-process cases pinned in
  `tests/test_agent_names_workflow.py`.
- Do not port mutation paths such as `claim_agent_name()` in this subphase. They write `agent_meta.json` and need a
  separate read/write consistency audit.
- Add a small benchmark scenario with many artifact dirs to compare current direct lookup vs snapshot-backed lookup
  under Python and Rust backends.

Exit criteria:

- Existing name-resolution tests pass.
- `SASE_CORE_BACKEND=rust pytest -k "agent_names or agent_ref_resolution"` passes when the extension is installed.
- Benchmark handoff states whether Rust snapshot improves name lookup enough to keep using the facade in hot paths.

### Phase 3E: CLI Agent Listing on the Scan Snapshot

Goal: move `sase agents` running/all listing onto the scan snapshot without changing output shape.

Write scope:

- `sase_100/src/sase/agent/running.py`.
- `sase_100/tests/main/test_agents_handler.py`.
- Focused tests for `list_running_agents()` / `list_all_agents()` if needed.
- `sase_100/tests/perf/bench_agent_scan.py`.

Work:

- Rework `list_running_agents()` to use scan records for `agent_meta.json`, `done.json`, `running.json`,
  `workflow_state`, and `raw_xprompt.md` prompt snippets where the wire contract provides them.
- Keep workspace-number lookup from RUNNING fields in Python for non-home projects.
- Keep PID liveness validation in Python.
- Rework `list_all_agents()` to reuse one scan snapshot for both running and recently completed agents.
- Preserve existing filters:
  - skip completed entries in `list_running_agents()`
  - skip parent-timestamp follow-up duplicates
  - skip workflow orchestrators with `appears_as_agent=False`
  - skip `outcome == "noop"`
  - keep per-project completed-agent cap semantics
  - preserve duration/status/model/provider/name/prompt fields
- Extend the benchmark to include CLI list operations before and after integration.

Exit criteria:

- Existing CLI handler tests pass.
- A focused benchmark shows the total listing cost in Python backend and Rust backend.
- If Rust does not improve total listing cost, document the blocker and keep the facade path opt-in.

### Phase 3F: TUI Artifact and Workflow Loader Integration

Goal: make the Agents tab refresh path use one artifact snapshot instead of independently walking done-agent and
workflow trees.

Write scope:

- `sase_100/src/sase/ace/tui/models/_loaders/_artifact_loaders.py`.
- `sase_100/src/sase/ace/tui/models/_loaders/_workflow_loaders.py`.
- `sase_100/src/sase/ace/tui/models/_loaders/__init__.py`.
- `sase_100/src/sase/ace/tui/models/agent_loader.py` if passing a precomputed snapshot is needed.
- Existing TUI loader/dedup tests under `sase_100/tests/ace/tui/` and root-level agent-loader tests.

Work:

- Add snapshot-aware loader helpers rather than replacing all existing direct loaders in one edit. Suggested shape:
  - `load_done_agents_from_snapshot(snapshot, bug_by_cl_name, cl_by_cl_name)`
  - `load_workflow_states_from_snapshot(snapshot)`
  - `load_workflow_agent_steps_from_snapshot(snapshot)`
  - `load_running_home_agents_from_snapshot(snapshot)`
- Update `_load_agents_from_all_sources()` to acquire one artifact scan snapshot near the top and pass it to the
  snapshot-aware loaders.
- Preserve direct Python loader functions as fallback/test helpers until at least one release cycle after the Rust path
  is trusted.
- Keep ChangeSpec field loaders (`HOOKS`, `MENTORS`, `COMMENTS`) in Python. They are not artifact filesystem scans.
- Preserve current enrichment semantics:
  - `agent_meta.json` wins for model/provider/name/wait/plan/retry fields
  - `waiting.json` overrides `agent_meta.json` wait fields
  - prompt-step `meta_*` values enrich parent workflows
  - plan path and diff path extraction match current backward-compatible behavior
  - workflow status maps `waiting_hitl`, `completed`, `failed`, and active dead-PID states the same way
- Keep dedup and status override logic unchanged initially. This phase should only change where artifact metadata comes
  from, not how `Agent` objects are merged or displayed.

Exit criteria:

- Existing agent-loader, workflow-loader, dedup, and Agents tab tests pass under Python backend.
- With the Rust extension installed, `SASE_CORE_BACKEND=rust` passes the same focused tests.
- Agents tab refresh benchmark shows whether the Rust snapshot reduces end-to-end refresh time after `Agent` adaptation
  and dedup.

### Phase 3G: Cache, Streaming Decision, and First-Frame Experiment

Goal: decide whether the snapshot API is enough or whether Phase 3 needs a batch-streaming API for user-visible first
frame latency.

Write scope:

- `../sase-core` scanner internals and PyO3 binding only if streaming is justified.
- `sase_100/src/sase/core/agent_scan_facade.py`.
- TUI loading path only if consuming batches is justified by measurement.
- Benchmark/handoff documentation.

Work:

- Measure:
  - Rust scan time before PyO3 conversion
  - PyO3 conversion time
  - Python adaptation from wire records to `Agent` / `WorkflowEntry`
  - dedup/status override time after adaptation
  - first-frame time in the TUI loader if available
- If snapshot mode clears the research gate, do not implement streaming in Phase 3. Keep the simpler API.
- If first-frame latency is still poor while Rust scan itself is fast, add a bounded batch API:
  - Rust scans in parallel and sends sorted-ish batches through a bounded channel.
  - PyO3 exposes a pull API such as `scan_agent_artifact_batches(root, options, batch_size)`.
  - Python consumes batches inside the existing `asyncio.to_thread` loader or a small iterator wrapper.
- Avoid one Python callback per artifact file. The batch size should be coarse enough to keep FFI overhead low.

Exit criteria:

- A written go/no-go decision for streaming exists.
- If streaming is implemented, snapshot and streaming results have parity tests against the same fixture corpus.
- If streaming is skipped, the reason is benchmark-backed.

### Phase 3H: Verification, Rollout Decision, and Handoff

Goal: close Phase 3 with a defensible default-backend decision and clear next steps.

Write scope:

- `sase_100/sdd/research/202604/rust_backend_phase3_agent_scan_handoff.md` or a plan/status document.
- `sase_100/docs/rust_backend.md`.
- `sase_100/tests/perf/bench_agent_scan.py`.
- `../sase-core/README.md` if user-facing Rust backend commands changed.

Work:

- Run Python-side checks:
  - `just install` if the workspace has not been installed recently
  - focused agent scan/name/running/TUI loader tests
  - `just rust-install`
  - `just bench-agent-scan` if a Justfile target is added, otherwise the benchmark script directly
  - `just check` before handoff because this repo changed
- Run Rust-side checks:
  - `cargo fmt --all -- --check`
  - `cargo clippy --workspace --all-targets -- -D warnings`
  - `cargo test --workspace`
- Measure at least:
  - name lookup over a large synthetic artifact tree
  - workflow completion check over the same tree
  - `list_all_agents()`
  - TUI `_load_agents_from_all_sources()` artifact/workflow portions
  - dual-run overhead
- Apply the research go gate:
  - first usable batch under 100 ms, or
  - total scan at least 2x faster end to end after PyO3 conversion and Python adaptation
- Decide whether to keep Rust scan opt-in or make it the default for selected operations. If only some operations clear
  the gate, default only those operations and leave the rest Python-backed.
- Do not remove the Python scanner or direct Python loaders in Phase 3.

Exit criteria:

- Phase 3 is complete when artifact scanning can run through Rust under an explicit backend flag, selected Python call
  sites have parity-backed integration, and benchmark evidence supports the rollout decision.
- The final handoff states whether Phase 4 (status state machine) should proceed next, or whether profiling points to a
  different bottleneck.

## Cross-Agent Dependency Order

1. Phase 3A must land first; it defines the contract, corpus, and benchmark target.
2. Phase 3B depends on 3A and can be implemented in `../sase-core` without touching Python behavior.
3. Phase 3C depends on 3B and wires Rust into the facade without moving product call sites yet.
4. Phase 3D and 3E both depend on 3C. They can run in parallel if their agents keep to the listed write scopes.
5. Phase 3F depends on 3C and benefits from 3D/3E lessons, but it does not need to wait for a default-backend decision.
6. Phase 3G depends on enough integration and measurement from 3D-3F to know whether streaming is justified.
7. Phase 3H lands last and should not be combined with feature work.

## Non-Goals

- Do not remove Python loaders or the Python backend.
- Do not flip `SASE_CORE_BACKEND` globally during implementation subphases.
- Do not port ChangeSpec RUNNING-field mutation, workspace claim mutation, agent killing, or dismissed-bundle mutation
  to Rust in Phase 3.
- Do not move plugin entry points, VCS provider behavior, or Textual UI code into Rust.
- Do not use Rust to read global configuration. Python supplies root paths and options.
- Do not implement streaming until snapshot parity and benchmarks prove it is needed.
- Do not require Rust for pure-Python installs.

## Key Risks

- FFI conversion can erase wins, as Phase 2 showed. Keep the scan wire compact and benchmark after conversion, not just
  inside Rust.
- Python liveness checks include process existence, stopped markers, and `/proc/<pid>/cmdline` guards. Porting that too
  early risks behavior drift and platform surprises.
- Artifact schemas are loose and historical. Rust structs must tolerate missing fields, extra fields, wrong field types,
  and malformed files without turning a single bad artifact into a failed scan.
- The TUI loader does more than scan: it adapts models, enriches metadata, dedups entries, and applies status overrides.
  Measure each segment separately so Rust is not blamed for Python adaptation costs.
- Ordering differences can create noisy UI diffs. Sort Rust results deterministically and keep Python's existing
  timestamp-descending display sort semantics.
- Snapshot freshness matters for running agents. Avoid long-lived persistent caches in Phase 3; rely on one fresh scan
  per refresh/request until invalidation is explicitly designed.

## Verification Matrix

Minimum focused tests by area:

- `pytest -k "agent_names or agent_ref_resolution"`
- `pytest -k "agent_names_workflow"`
- `pytest -k "agents_handler or list_all_agents or running_agents"`
- `pytest -k "agent_loader or workflow_states or workflow_loaders or done_agent_loader"`
- `pytest -k "core_facade or core_backend or dual_run"`

Full repo check after any `sase_100` production change:

```bash
just install
just check
```

Rust checks after any `../sase-core` change:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

If both repos change, run both sets before handoff.
