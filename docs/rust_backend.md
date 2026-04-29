# Optional Rust Backend (`sase_core_rs`)

A subset of sase's core APIs (currently `parse_project_bytes`, `parse_query` / `evaluate_query_many`,
`scan_agent_artifacts`, the status line helpers `read_status_from_lines` / `apply_status_update`, and the status
transition planner `plan_status_transition`) can be served by an optional Rust extension built from a sibling
[`sase-core`](https://github.com/sase-org/sase-core) repo. The Rust backend is **opt-in**: pure-Python installs keep
working with no Rust toolchain, and every `just rust-*` target degrades to a friendly no-op when the sibling repo is
absent.

`SASE_CORE_BACKEND=rust` is a hybrid per-operation mode: operations with shipped Rust bindings use Rust, while facade
APIs that are intentionally unported use their Python implementation. Missing bindings for shipped Rust operations still
raise `RustBackendUnavailableError`, so a stale or absent extension cannot make Rust mode appear to exercise Rust.

## Why a Rust Backend?

The `sase.core` package is a stable Python facade carved out specifically so individual operations can be re-served by
faster Rust implementations one at a time. Parsing project `.gp` files dominates many cold-path workloads (TUI startup,
large search results, axe lumberjack scans), so it is the first operation routed through this seam.

## Architecture

```
                ┌─────────────────────────────────────────────┐
                │              sase Python code               │
                └────────────────────┬────────────────────────┘
                                     │ calls
                                     ▼
                ┌─────────────────────────────────────────────┐
                │          sase.core (Python facade)          │
                │  parser_facade · query_facade · status_*    │
                └────────────┬───────────────────┬────────────┘
                             │                   │
              SASE_CORE_BACKEND=python   SASE_CORE_BACKEND=rust
                             │                   │
                             ▼                   ▼
                ┌──────────────────┐   ┌──────────────────────┐
                │  Python impl     │   │  sase_core_rs (PyO3) │
                │  (always present)│   │  optional extension  │
                └──────────────────┘   └──────────────────────┘
```

The facade lives at `src/sase/core/`:

| Module                      | Purpose                                                                              |
| --------------------------- | ------------------------------------------------------------------------------------ |
| `backend.py`                | `SASE_CORE_BACKEND` dispatcher; `is_rust_available()`; `RustBackendUnavailableError` |
| `parser_facade.py`          | `parse_project_file` compatibility API / Rust-eligible `parse_project_bytes` parser  |
| `wire.py`                   | Stable wire record types that cross the Python ↔ Rust boundary                       |
| `wire_conversion.py`        | Python `ChangeSpec` ↔ wire record serialization                                      |
| `dual_run.py`               | Optional Python+Rust comparison logging (`SASE_CORE_DUAL_RUN=1`)                     |
| `query_facade.py`           | Query parse / build / evaluate facade                                                |
| `status_facade.py`          | Status transition helpers facade                                                     |
| `graph_index_facade.py`     | `build_changespec_graph_index()` facade                                              |
| `agent_scan_facade.py`      | `scan_agent_artifacts()` snapshot facade (Phase 3)                                   |
| `agent_scan_wire.py`        | Stable wire records for the agent-artifact scan snapshot                             |
| `status_wire.py`            | Stable wire records for the status state machine (Phase 4)                           |
| `status_wire_conversion.py` | Python plan implementation + project-file → request-wire converter                   |

The Rust extension is a sibling repo at `../sase-core/`, organized as a Cargo workspace with a PyO3 crate at
`crates/sase_core_py/`.

## Installing the Rust Backend

Rust dev tools are required: install [rustup](https://rustup.rs/) so `cargo` is on `PATH`. Then clone the Rust core
beside this repo and build the PyO3 extension into the venv that runs `sase`. There are two common cases:

```bash
git clone https://github.com/sase-org/sase-core.git ../sase-core

# Dev workflow — installs into the repo .venv (used by `just test`, benchmarks, parity tests).
just rust-install

# Installed-sase workflow — installs into the uv-tool venv at $(uv tool dir)/sase
# so `SASE_CORE_BACKEND=rust sase ...` works for the user's installed `sase` CLI.
just rust-install-uv-tool
```

Both targets install `maturin` into the target venv on demand and run `maturin develop --release` inside
`../sase-core/crates/sase_core_py/`. After either succeeds, `python -c "import sase_core_rs"` works inside that venv.

For other install methods (pipx, system Python, a custom venv), pass the venv path explicitly:

```bash
just rust-install /path/to/venv
```

`maturin develop --release` rebuilds and replaces the extension on every run, so re-running these targets after a
`../sase-core` update is the supported way to refresh an existing install.

## Selecting the Backend at Runtime

| Env var              | Values                     | Effect                                                                                                                                                       |
| -------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SASE_CORE_BACKEND`  | `python` (default), `rust` | Selects which implementation each dispatched operation uses. Rust mode uses Rust for shipped bindings and Python for explicitly unported operations.         |
| `SASE_CORE_DUAL_RUN` | `1` / `true` / `yes`       | Run both impls on every dispatched op; log mismatches to `~/.sase/perf/core_dual_run.jsonl`. The Python result is always returned while dual-run is enabled. |

Selecting `SASE_CORE_BACKEND=rust` when a shipped Rust operation's binding is unavailable raises
`RustBackendUnavailableError` rather than silently falling back. For example, `parse_project_bytes`, `parse_query`,
`evaluate_query_many`, `scan_agent_artifacts`, `read_status_from_lines`, `apply_status_update`, and
`plan_status_transition` require `sase_core_rs` to expose the corresponding binding. Query context/per-row evaluation,
graph-index construction, and the side-effecting `transition_changespec_status` are intentionally unported today and
fall back to Python under Rust mode. `transition_changespec_status` keeps an explicit `rust_unavailable="python"`
fallback because dual-running the full transition would duplicate every disk-bound side effect; the pure decision step
inside it routes through Rust via `plan_status_transition` instead.

`is_rust_available()` is a lazy, forgiving probe: an `ImportError` simply reports `False` so a pure-Python install is
never broken; other import-time failures propagate so a _misbuilt_ wheel surfaces immediately.

`parse_project_file()` stays Python-only even when Rust is available — the Rust binding consumes bytes, and re-reading
the file from disk would defeat the perf rationale. Callers that want the Rust path read the file themselves and call
`parse_project_bytes()`.

## Justfile Targets

Each target prints a friendly skip message when `../sase-core` is absent and exits 0, so pure-Python contributors are
never blocked.

| Target                      | Description                                                                                                 |
| --------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `just rust-install`         | Build + install `sase_core_rs` via `maturin develop --release` (installs maturin if missing)                |
| `just rust-install-uv-tool` | Same as `rust-install` but targets `$(uv tool dir)/sase` for users who installed sase via `uv tool install` |
| `just rust-test`            | `cargo test --workspace` in `../sase-core`                                                                  |
| `just rust-fmt`             | Auto-format Rust sources with `cargo fmt --all`                                                             |
| `just rust-fmt-check`       | CI-mode formatting verification (`cargo fmt --all -- --check`)                                              |
| `just rust-clippy`          | `cargo clippy --workspace --all-targets -- -D warnings`                                                     |
| `just rust-check`           | Combined Rust check: `rust-fmt-check` + `rust-clippy` + `rust-test`                                         |
| `just rust-bench`           | Run the direct-parser Rust benchmark (`cargo run --release --example bench_parse`)                          |
| `just bench-core`           | Python `parse_project_bytes` benchmark across all available backends                                        |
| `just bench-agent-scan`     | Python agent-artifact scan benchmark vs current direct loaders (Phase 3 baseline)                           |

## Benchmarking

`just bench-core` runs `tests/perf/bench_core_parse.py` and reports per-backend timings:

- **Python-direct** — calls the on-disk parser with no facade overhead.
- **Python-facade** — routes through `sase.core.parse_project_bytes` with the Python impl.
- **Rust direct** — calls into `sase_core_rs` directly (only when the extension is importable).
- **Rust-facade** — routes through `sase.core.parse_project_bytes` with the Rust impl.
- **Dual-run overhead** — facade with `SASE_CORE_DUAL_RUN=1` (both impls executed; comparison logged).

`just rust-bench` runs a Rust-only `cargo bench` example for measurements that exclude the Python interpreter from the
loop.

## Roadmap

- **Phase 0** _(complete)_ — Python facade carved out (`sase.core`); golden contract tests; backend boundary documented;
  existing public APIs routed through the facade with no behavior change.
- **Phase 1** _(complete)_ — Optional `sase_core_rs` extension wired into `parse_project_bytes`; cross-repo parity gate;
  dev-workflow Justfile targets; Python core parse benchmark.
- **Phase 2A** _(complete)_ — Query wire contract, golden corpus, and benchmark in place; Rust query backend opt-in
  pending the rollout decision in Phase 2F.
- **Phase 3A** _(complete)_ — Agent-artifact scan wire contract (`agent_scan_wire.py`), pure-Python facade
  (`agent_scan_facade.py`), golden parity tests against a synthetic corpus (`tests/agent_scan_golden/`), and a baseline
  benchmark (`tests/perf/bench_agent_scan.py`, `just bench-agent-scan`). No Rust code yet — Phase 3B implements the
  pure-Rust scanner in `../sase-core`.
- **Phase 3B** _(complete)_ — Pure-Rust snapshot scanner in `../sase-core/crates/sase_core/src/agent_scan/`. Mirrors the
  Phase 3A wire records, produces the same JSON shape, and ships its own fixture-built parity tests so `cargo test`
  works without a Python toolchain.
- **Phase 3C** _(complete)_ — `sase_core_rs.scan_agent_artifacts(projects_root, options)` PyO3 binding releases the GIL
  during the filesystem walk and returns the snapshot as a plain dict. The `scan_agent_artifacts` facade registers the
  Rust impl whenever the extension is importable; `SASE_CORE_BACKEND=rust` walks the corpus through Rust and
  `SASE_CORE_DUAL_RUN=1` logs Python/Rust comparison records to `~/.sase/perf/core_dual_run.jsonl`. Callers still
  receive `AgentArtifactScanWire` dataclasses on either backend.
- **Phase 3D** _(complete)_ — `find_named_agent` and `is_workflow_complete` consume the snapshot facade instead of
  walking project directories directly. Liveness / dismissed-bundle fallback semantics stay in Python; only the
  artifact-tree read is rerouted.
- **Phase 3E** _(complete)_ — `sase agents` running/all listing (`list_running_agents`, `list_all_agents`) consumes one
  snapshot per call and adapts records into the same output shape as before. PID liveness and workspace-claim parsing
  remain Python-side.
- **Phase 3F** _(complete)_ — TUI Agents-tab refresh (`_load_agents_from_all_sources`) acquires one
  `scan_agent_artifacts` snapshot and feeds every artifact / workflow loader from it. Direct Python loaders are kept as
  fallback / test helpers.
- **Phase 3G** _(complete)_ — Snapshot-pipeline breakdown measurements added to `bench_agent_scan.py`
  (`scan_rust_to_dict`, `scan_rust_dict_to_wire`, `scan_rust_facade`); decision recorded in
  `plans/202604/rust_backend_phase3_agent_scan_phase3g_handoff.md`: keep the snapshot API, do **not** implement a batch
  streaming API in Phase 3, do **not** introduce a long-lived artifact cache. Snapshot mode clears the research gate at
  typical workloads and the very-large-tree gap is dominated by Rust filesystem walk itself, which streaming cannot
  reduce.
- **Phase 3H** _(complete)_ — Verification, rollout decision, and Phase 3 close-out recorded in
  `plans/202604/rust_backend_phase3_agent_scan_phase3h_handoff.md`. Rollout: `SASE_CORE_BACKEND` stays `python` by
  default; the Rust path is shipped, parity-tested, and **opt-in**. Rust scan is 1.25×–1.55× faster end-to-end at the
  workloads measured but does not clear the 2× research gate at the worst real workload (`~/.sase/projects`, 6.5k
  records), and no per-operation default-Rust override is justified — `is_workflow_complete` is structurally slower on
  the snapshot path because it removes the Python short-circuit. Phase 4 (status state machine) is still on the table
  but should be re-profiled against a realistic home tree before committing.
- **Phase 4C** _(complete)_ — Pure Rust status module landed in `../sase-core/crates/sase_core/src/status/` (constants,
  name suffix helpers, line-based field updates, and the pure-decision planner) with serde-compatible wire structs that
  mirror Phase 4B byte-for-byte. PyO3 bindings on `sase_core_rs` expose `remove_workspace_suffix`,
  `is_valid_status_transition`, `read_status_from_lines`, `apply_status_update`, and `plan_status_transition`. No
  production caller is routed through Rust yet — `status_facade.py` continues to dispatch every operation to Python.
- **Phase 4D** _(complete)_ — `status_facade.read_status_from_lines` and `status_facade.apply_status_update` register
  the Rust bindings as `rust_impl` whenever `sase_core_rs` is importable. `SASE_CORE_BACKEND=rust` routes both line
  helpers through Rust; missing bindings under rust mode raise `RustBackendUnavailableError` (the line helpers are now
  classified as shipped Rust operations). `SASE_CORE_DUAL_RUN=1` runs both impls and logs comparison records to
  `~/.sase/perf/core_dual_run.jsonl`. `transition_changespec_status` stays on Python with the
  `rust_unavailable="python"` fallback; the Rust planner integration is the Phase 4E target.
- **Phase 4E** _(complete)_ — `status_facade.plan_status_transition` registers the Rust planner as `rust_impl` whenever
  `sase_core_rs` is importable; `SASE_CORE_BACKEND=rust` runs the pure decision step in Rust and missing bindings raise
  `RustBackendUnavailableError`. `transition_changespec_status_python` was refactored into three explicit stages —
  in-lock input gathering (`build_status_transition_request`), pure decision (`plan_status_transition` facade), and
  side-effect execution (STATUS line rewrite, mentor flag mutation, suffix renames, archive moves, timestamp recording)
  — so the planner is the only step that crosses the Rust boundary. Side effects remain entirely on Python and run
  exactly once per transition, regardless of backend. `SASE_CORE_DUAL_RUN=1` compares plans before any side effects fire
  (a failing Rust plan short-circuits the transition before the atomic write).
- **Phase 4B** _(complete)_ — Status wire contract pinned in `src/sase/core/status_wire.py`
  (`StatusTransitionRequestWire` / `StatusTransitionPlanWire` / `ChangespecChildWire`, plus `StatusFieldReadWire` and
  `StatusFieldUpdateWire` for the line helpers). The Python decision engine
  `plan_status_transition_python(request) -> StatusTransitionPlanWire` and the project-file converter
  `build_status_transition_request(...)` live in `src/sase/core/status_wire_conversion.py`. Golden parity tests at
  `tests/test_core_status_wire.py` lock down validation, workspace/legacy suffix stripping, parent/child constraints,
  Ready→Draft suffix-append planning, Draft/WIP→Ready suffix-strip planning, terminal statuses, and `validate=False`.
  `tests/test_core_status_lines.py` pins the `read_status_from_lines` / `apply_status_update` line behaviour. No
  production call site uses the new planner yet — Phase 4D will route the line helpers and Phase 4E will route
  `plan_status_transition` through the facade with dual-run logging.
- **Future phases** — Additional facade operations (graph index, status helpers, agent-status state machine) become
  candidates for Rust re-implementation as they show up in profiles. Re-evaluate streaming only if a workload appears
  where Rust scan time is small but Python adaptation dominates.

The migration strategy intentionally keeps the Rust core as a single crate that can be exposed through three different
binding layers: PyO3 for the TUI/CLI (today), uniffi for mobile, and wasm for the web. See
`research/202604/rust_backend_migration.md` for the broader plan.
