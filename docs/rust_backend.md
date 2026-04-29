# Rust Backend (`sase_core_rs`)

> **Phase 8 in progress.** Phase 8 of the Rust backend migration is removing the `SASE_CORE_BACKEND` /
> `SASE_CORE_DUAL_RUN` plumbing entirely; ported facades will call `sase_core_rs` directly through the strict loader in
> `src/sase/core/rust.py`. This document still describes the Phase 6/7 dispatcher; sections that reference
> `SASE_CORE_BACKEND`, `SASE_CORE_DUAL_RUN`, or `dispatch` will be rewritten in Phase 8G. Plan:
> `plans/202604/rust_backend_phase8.md`.

A subset of sase's core APIs (currently `parse_project_bytes`, `parse_query` / `evaluate_query_many`,
`scan_agent_artifacts`, the status line helpers `read_status_from_lines` / `apply_status_update`, the status transition
planner `plan_status_transition`, and the Git query parsers `parse_git_name_status_z` / `parse_git_branch_name` /
`derive_git_workspace_name` / `parse_git_conflicted_files` / `parse_git_local_changes`) is served by a Rust extension
distributed as `sase-core-rs` on PyPI and built from the sibling [`sase-core`](https://github.com/sase-org/sase-core)
repo.

Starting in Phase 6, `sase` declares `sase-core-rs` as a runtime dependency, so a normal `pip install sase` (or
`uv tool install sase`) on a supported platform installs the Rust extension automatically — no Rust toolchain required.
**Starting in Phase 6F, Rust is the default backend**: an unset `SASE_CORE_BACKEND` selects Rust for shipped operations.
Pure-Python execution remains available through Phase 7 with `SASE_CORE_BACKEND=python`, which does not require
`sase_core_rs` to be importable.

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
              SASE_CORE_BACKEND=python   SASE_CORE_BACKEND=rust (default)
                             │                   │
                             ▼                   ▼
                ┌──────────────────┐   ┌──────────────────────┐
                │  Python impl     │   │  sase_core_rs (PyO3) │
                │  (escape hatch)  │   │  default extension   │
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
| `git_query_facade.py`       | Pure Git query parsers facade (Phase 5)                                              |
| `git_query_wire.py`         | Stable wire records for the Git query parsers (Phase 5)                              |

The Rust extension is a sibling repo at `../sase-core/`, organized as a Cargo workspace with a PyO3 crate at
`crates/sase_core_py/`.

## Installing the Rust Backend

### Released `sase` (recommended for users)

`sase-core-rs` is a regular runtime dependency of `sase`. A standard install pulls a prebuilt wheel for the host
platform from PyPI; no Rust toolchain is needed:

```bash
pip install sase
# or
uv tool install sase
```

The Phase 6 release matrix ships wheels for CPython 3.12+ on Linux x86_64, Linux aarch64, macOS universal2, and Windows
x86_64. After install, `python -c "import sase_core_rs"` succeeds inside the same venv that runs `sase`.

### Source / development workflow

`just install` automatically builds and installs `sase_core_rs` from a sibling `../sase-core` checkout when one exists
and a Rust toolchain (`cargo`) is on `PATH`. This satisfies the `sase-core-rs` runtime dependency from local source so
the editable `sase` install does not have to round-trip through PyPI:

```bash
git clone https://github.com/sase-org/sase-core.git ../sase-core
just install     # builds sase_core_rs from ../sase-core, then installs sase in editable mode
```

`just rust-install` remains the explicit way to (re)build only the extension, and `just rust-install-uv-tool` targets
the uv-tool venv at `$(uv tool dir)/sase` for users who installed `sase` via `uv tool install` and want the latest local
Rust code instead of the published wheel:

```bash
just rust-install                 # repo .venv (used by `just test`, benchmarks, parity tests)
just rust-install-uv-tool         # $(uv tool dir)/sase
just rust-install /path/to/venv   # any other venv (pipx, system Python, custom location)
```

Both targets install `maturin` into the target venv on demand and run `maturin develop --release` inside
`../sase-core/crates/sase_core_py/`, so re-running them after a `../sase-core` update is the supported way to refresh an
existing source install.

### Pure-Python fallback

A contributor without a Rust toolchain and without a sibling `../sase-core` checkout can still develop against `sase`:
the runtime dependency on `sase-core-rs` resolves to the published PyPI wheel, but `SASE_CORE_BACKEND=python` keeps the
extension out of the dispatch path so a misbuilt or otherwise unloadable wheel does not block work. This escape hatch
remains supported through Phase 7.

## Selecting the Backend at Runtime

| Env var              | Values                     | Effect                                                                                                                                                                                                                                                                                                                                                 |
| -------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SASE_CORE_BACKEND`  | `rust` (default), `python` | Selects which implementation each dispatched operation uses. Rust mode uses Rust for shipped bindings and Python for explicitly unported operations. `python` is the temporary escape hatch through Phase 7.                                                                                                                                           |
| `SASE_CORE_DUAL_RUN` | `1` / `true` / `yes`       | Parity/safety rail: run both impls on every dispatched op and log comparison records to `~/.sase/perf/core_dual_run.jsonl`. The Python result is always returned while dual-run is enabled. Used by the CI parity gate (`tests/parity/dual_run_parity.py`) and available locally for ad-hoc verification, not intended for normal production sessions. |

Selecting `SASE_CORE_BACKEND=rust` when a shipped Rust operation's binding is unavailable raises
`RustBackendUnavailableError` rather than silently falling back. The error names the operation, the `sase_core_rs`
extension, and the `SASE_CORE_BACKEND=python` escape hatch.

### Backend Health Check

`sase core health` is the scriptable answer to "is the active backend loadable and working?". The command resolves the
selected backend, tries to import `sase_core_rs`, calls a single shipped binding (`parse_query("status:Ready")`) when
the extension is loaded, and reports module path / version / Python version / platform tag in one block. Two output
modes:

```bash
sase core health        # human-readable, line-oriented
sase core health -j     # machine-readable JSON (alias: --json)
```

Exit codes:

| Selected backend | Extension state                     | `status` | Exit |
| ---------------- | ----------------------------------- | -------- | ---- |
| unset / `rust`   | importable, `parse_query` works     | `ok`     | 0    |
| unset / `rust`   | missing or misbuilt                 | `error`  | 1    |
| unset / `rust`   | importable but `parse_query` raises | `error`  | 1    |
| `python`         | any                                 | `ok`     | 0    |

Under explicit `SASE_CORE_BACKEND=python`, a missing or misbuilt `sase_core_rs` is non-fatal — Python mode is the
documented escape hatch through Phase 7. A misbuilt wheel that fails to import with a non-`ImportError` is surfaced in
the `error` / `error_kind` fields rather than silently masked.

Release jobs and CI install-smokes call `sase core health` instead of probing `import sase_core_rs` and a binding by
hand: it is the same check, but its exit code is the contract.

### Backend Contract: Shipped vs. Unported Operations

Phase 6C audited every `dispatch(...)` call site under `src/sase/core/` and classifies each operation as either
**shipped** (a Rust binding is registered when `sase_core_rs` exposes it; missing binding under Rust mode raises
`RustBackendUnavailableError`) or **unported** (Python is the only implementation; `rust_unavailable="python"` keeps the
operation working under Rust mode). The classification is pinned by `tests/test_core_facade/test_backend_contract.py`,
which fails if a new `dispatch(operation=...)` call site is added without explicit classification.

| Operation                      | Facade module           | Class    | Rust mode behavior with no binding                     |
| ------------------------------ | ----------------------- | -------- | ------------------------------------------------------ |
| `parse_project_bytes`          | `parser_facade.py`      | shipped  | raises `RustBackendUnavailableError`                   |
| `parse_query`                  | `query_facade.py`       | shipped  | raises `RustBackendUnavailableError`                   |
| `evaluate_query_many`          | `query_facade.py`       | shipped  | raises `RustBackendUnavailableError`                   |
| `scan_agent_artifacts`         | `agent_scan_facade.py`  | shipped  | raises `RustBackendUnavailableError`                   |
| `read_status_from_lines`       | `status_facade.py`      | shipped  | raises `RustBackendUnavailableError`                   |
| `apply_status_update`          | `status_facade.py`      | shipped  | raises `RustBackendUnavailableError`                   |
| `plan_status_transition`       | `status_facade.py`      | shipped  | raises `RustBackendUnavailableError`                   |
| `parse_git_name_status_z`      | `git_query_facade.py`   | shipped  | raises `RustBackendUnavailableError`                   |
| `parse_git_branch_name`        | `git_query_facade.py`   | shipped  | raises `RustBackendUnavailableError`                   |
| `derive_git_workspace_name`    | `git_query_facade.py`   | shipped  | raises `RustBackendUnavailableError`                   |
| `parse_git_conflicted_files`   | `git_query_facade.py`   | shipped  | raises `RustBackendUnavailableError`                   |
| `parse_git_local_changes`      | `git_query_facade.py`   | shipped  | raises `RustBackendUnavailableError`                   |
| `build_query_context`          | `query_facade.py`       | unported | runs Python (`rust_unavailable="python"`)              |
| `evaluate_query`               | `query_facade.py`       | unported | runs Python (`rust_unavailable="python"`)              |
| `evaluate_query_with_context`  | `query_facade.py`       | unported | runs Python (`rust_unavailable="python"`)              |
| `build_changespec_graph_index` | `graph_index_facade.py` | unported | runs Python (`rust_unavailable="python"`)              |
| `transition_changespec_status` | `status_facade.py`      | unported | runs Python (`rust_unavailable="python"`, no dual-run) |

`transition_changespec_status` keeps an explicit `rust_unavailable="python"` fallback because dual-running the full
transition would duplicate every disk-bound side effect; the pure decision step inside it routes through Rust via
`plan_status_transition` instead. Dual-run logging is also a no-op for any operation without a registered `rust_impl`,
so the unported set never appears in `~/.sase/perf/core_dual_run.jsonl`.

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

## Performance

Phase 7 captured a deliberate measurement pass after the Phase 6F default flip: every shipped Rust-backed core operation
under explicit Python and default Rust, plus the user-facing TUI / CLI surfaces named in the migration plan. The raw
JSON artifacts live under `plans/202604/perf_artifacts/`; tables in this section summarize the medians a reader should
expect when running the same harnesses against the same backend.

### Workstation profile

All numbers below come from a single capture machine (Phase 7B + 7C, 2026-04-29):

- Linux x86_64, CPython 3.14.3.
- `sase-core-rs` editable install built from a sibling `../sase-core/` checkout via `just rust-install`; metadata in
  every artifact's `metadata.rust_module_path` / `metadata.rust_module_version` records the exact extension probed.
- Default-Rust runs use an unset `SASE_CORE_BACKEND`; explicit-Python runs set `SASE_CORE_BACKEND=python` at process
  launch (env-pinned, never toggled mid-process).
- Sample sizes per scenario are recorded inline below and pinned in each artifact's `metadata.runs` / `metadata.warmup`.
  End-to-end TUI/CLI runs are 10–12 samples; microbenchmarks are 20–200 samples per scenario.

Read the tables as: `speedup` is `python_median / rust_median`, so `2.0×` means default Rust is twice as fast as
explicit Python on that workload, and `0.5×` means default Rust is half as fast.

### Core operations (Phase 7B microbenchmarks)

Driver: `tests/perf/phase7/run_phase7b.py`. One `*_summary.json` artifact per shipped operation under
`plans/202604/perf_artifacts/rust_backend_phase7_<op>_summary.json`; each artifact embeds the Phase 7A `Phase7Metadata`
envelope, the relevant scenario summaries, and pre-computed `(workload, scenario)` comparison rows.

| Operation                    | Workload                 | Scenario                   | py median | rust median |   speedup |
| ---------------------------- | ------------------------ | -------------------------- | --------: | ----------: | --------: |
| `parse_project_bytes`        | golden_myproj            | facade                     |    296 µs |      124 µs |  **2.4×** |
| `parse_project_bytes`        | synthetic_200_specs      | facade                     |   26.7 ms |     19.1 ms |  **1.4×** |
| `parse_query`                | parse_only               | direct                     |   12.3 µs |      5.8 µs |  **2.1×** |
| `evaluate_query_many`        | synthetic_1000_specs     | facade                     |   4.03 ms |     74.7 ms | **0.05×** |
| `evaluate_query_many`        | synthetic_10000_specs    | facade                     |   68.1 ms |      831 ms | **0.08×** |
| `scan_agent_artifacts`       | synthetic_6p_200pp       | scan_facade                |    145 ms |      120 ms | **1.21×** |
| `read_status_from_lines`     | synthetic_200_specs_pure | read_status_from_lines     |    182 µs |      349 µs |     0.52× |
| `apply_status_update`        | synthetic_200_specs_pure | apply_status_update        |    256 µs |      377 µs |     0.68× |
| `plan_status_transition`     | synthetic_200_specs_pure | plan_status_transition     |   8.66 µs |    18.78 µs |     0.46× |
| `parse_git_name_status_z`    | synthetic_medium (1k)    | parse_git_name_status_z    |    626 µs |      880 µs |     0.71× |
| `parse_git_branch_name`      | normalizers_x4           | parse_git_branch_name      |   8.74 µs |    10.40 µs |     0.84× |
| `derive_git_workspace_name`  | normalizers_x5           | derive_git_workspace_name  |   11.7 µs |     13.5 µs |     0.87× |
| `parse_git_conflicted_files` | normalizers_50_lines     | parse_git_conflicted_files |   5.35 µs |     6.83 µs |     0.78× |
| `parse_git_local_changes`    | normalizers_150_entries  | parse_git_local_changes    |   4.51 µs |     5.68 µs |     0.79× |

The full per-percentile data (min / median / p95 / max) is in each artifact's `workloads[].baseline` /
`workloads[].candidate`; the `comparisons[]` rows pre-compute `ratio`, `speedup`, and `percent_delta` for every
`(workload, scenario)` pair.

### End-to-end TUI / CLI surfaces (Phase 7C)

Driver: `tests/perf/bench_phase7_e2e.py`. One artifact per `(surface, backend)` invocation under
`plans/202604/perf_artifacts/rust_backend_phase7_<surface>_<backend>.json`; the home-tree `sase agents status` rows sit
in the gitignored `plans/202604/perf_artifacts/local_only/` dir because they reflect a workstation-specific tree.

| Surface                      | Workload                          | runs | default_rust | explicit_python |   speedup |
| ---------------------------- | --------------------------------- | ---- | -----------: | --------------: | --------: |
| `sase_run_startup`           | `import_run_query_cold`           | 12   |     249.3 ms |        252.6 ms |     1.01× |
| `sase_agents_status_listing` | `synthetic_8_projects_25_agents`  | 12   |     298.5 ms |        774.5 ms | **2.59×** |
| `sase_agents_status_listing` | `home_tree` (local-only artifact) | 5    |     885.8 ms |      1,799.7 ms | **2.03×** |
| `sase_ace_cold_open`         | `synthetic_100_cs_50_agents`      | 10   |   1,472.5 ms |      1,237.4 ms |     0.84× |

`sase_run_startup` measures cold subprocess `python -c "from sase.main.query_handler._query import run_query"`; it
deliberately stops at the dispatcher's provider boundary, never resolves a provider, never touches the network, and
never claims a workspace. The `metadata.extra.boundary` field in the artifact records this scope so a future agent can
push the boundary further toward provider resolution without invalidating the comparison.

### Where Rust helps, where Rust does not help yet

**Wins that users feel:**

- `sase agents status -j` cold listing is the headline default-Rust win — ~2.6× on the synthetic 8×25 tree and ~2.0× on
  this workstation's home tree. The cold subprocess wall-time is dominated by `scan_agent_artifacts`, which Phase 3
  ported to Rust. The `local_only/` home-tree artifacts confirm the synthetic numbers are not a fixture artifact; they
  generalise to a realistic `~/.sase/projects/` of comparable depth.
- `parse_project_bytes` is a clean ~2.4× win on small files and ~1.4× on a 200-spec synthetic file. Both the raw Rust
  call and the dispatched `facade` path beat Python at every workload size measured, so the win survives PyO3 wire
  conversion.
- `parse_query` direct parsing is a ~2.1× win on the parse-only workload. The `synthetic_*_specs` evaluator workloads in
  `bench_core_query` deliberately fold parse cost into `evaluate_query_many` and so do not re-time `rust_facade_parse`;
  that is intentional, not a regression.

**Honest negative results (do not paper over):**

- `evaluate_query_many` is dramatically slower under default Rust than the optimized Python batch path (8 µs/spec vs 4–7
  µs/spec at 100 specs, scaling worse at 10k). The cause is per-call wire conversion (`changespec_to_wire` +
  `to_json_dict`) for every spec on every facade call — marshaling overhead dominates the actual evaluation. The shipped
  Rust path is **not** an end-to-end win on the default backend today; the win is upstream (parse) and inside the TUI's
  other pipelines. Phase 8 should not remove the Python implementation until either the wire conversion is amortized or
  the comparison is rerun against the optimized batch path.
- `sase ace` cold open is ~19 % slower under default Rust on the synthetic Pilot harness. The harness mocks
  `find_all_changespecs`, so the Rust scan/parse hot paths are not exercised; what remains is AceApp / Pilot constructor
  cost plus per-call PyO3 dispatch overhead at small inputs. Phase 7E keeps this surface out of the hard PR floor; treat
  it as a known small-input dispatch tax, not a regression in the routed Rust operation.
- The status-line helpers (`read_status_from_lines`, `apply_status_update`, `plan_status_transition`) and the small Git
  normalizers (`parse_git_branch_name`, `derive_git_workspace_name`, `parse_git_conflicted_files`,
  `parse_git_local_changes`) are 13–55 % slower under default Rust than Python on the inputs they actually see in
  production. These are dispatch-overhead-dominated cores at sub-10-µs absolute cost; the gap is single-digit
  microseconds and is invisible against the surrounding subprocess / atomic-write cost. Phase 4 / Phase 5 accepted this
  — those operations route through Rust to keep the facade contract honest, not because Rust is faster on them.
- `parse_git_name_status_z` is consistently ~25–30 % slower under default Rust on synthetic streams, but the end-to-end
  `git diff --name-status -z` workloads in `bench_git_query_ops` show parse is single-digit microseconds next to
  multi-millisecond subprocess cost, so the delta is invisible to users.
- `sase run` startup is backend-neutral at the cold-import scope: the cost users pay before the dispatcher can call any
  LLM is dominated by Python interpreter startup + sase package import, and routing through Rust vs Python inside
  `sase.core` does not show up because `run_query` is not exercised at import time. Treat `sase_run_startup` as an
  import-bloat sentinel rather than a Rust win/loss surface.

### Phase 7 support note

Use this checklist when triaging a Phase 6/7 backend issue:

- **Confirm which backend is active.** `sase core health` (or `sase core health -j` for scripts) prints the resolved
  backend, the `sase_core_rs` module path / version, and the result of a single shipped binding call. Exit code 0 means
  Rust mode loaded and worked; non-zero means default Rust failed to load and the user is now relying on the Phase 6/7
  escape hatch. Explicit `SASE_CORE_BACKEND=python sase core health` always exits 0 because Python mode does not require
  `sase_core_rs` to be importable.
- **Read the dual-run logs.** `SASE_CORE_DUAL_RUN=1` writes per-call comparison records to
  `~/.sase/perf/core_dual_run.jsonl`. Each record contains `operation`, `match`, durations for both impls, and the first
  divergent path when `match: false`. The CI `parity-gate` job uploads the same shape as `parity-artifacts/` so a
  regression can be diagnosed without a local repro. Dual-run is parity tooling, not a normal production mode — do not
  leave it on for everyday TUI launches.
- **Recognise a wheel-load failure.** A misbuilt or missing `sase_core_rs` under default Rust surfaces as
  `RustBackendUnavailableError` from a shipped operation, or as `sase core health` exit code 1 with `error_kind` /
  `error` fields naming the underlying `ImportError`. The publish-workflow `install-smoke` re-runs `sase core health` in
  both modes on every release and dumps `pip list` plus `sase_core_rs.__file__` / `__version__` on failure.
- **Use the temporary Python escape hatch when needed.** `export SASE_CORE_BACKEND=python` keeps the dispatcher off the
  Rust path for every shipped operation, including the operations whose Rust binding has failed to load. This is the
  documented escape hatch through Phase 7 only — Phase 8 deletes both the env var and the Python implementations once
  one release cycle has shown clean parity numbers and a stable performance floor.

## Verifying The Backend

A handful of commands cover "is my install healthy?" end-to-end:

```bash
sase core health             # default-Rust health: status + module path + version + platform
sase core health -j          # same, JSON for scripting
SASE_CORE_BACKEND=python sase core health   # confirm explicit-Python escape hatch works without sase_core_rs

just check                   # full lint + type + test pass on the active backend
just parity-check            # run tests/parity/dual_run_parity.py against the golden corpus + sanitized home tree
just rust-check              # cargo fmt --check + clippy + cargo test (requires sibling ../sase-core checkout)
```

The parity gate exits non-zero if any non-divergent shipped operation produces a `match: false` record, no records at
all, or a Rust-side exception. `parse_project_bytes` is the only documented divergence — the Python parser does not
track `source_span.end_line`; the gate still requires it to produce records, and `tests/test_core_parity_smoke.py` pins
the alternative byte-for-byte contract. The CI `parity-gate` job uploads `parity-artifacts/` (the JSONL log + summary)
on every run, so a regression can be inspected post-hoc.

CI also runs the full test suite on both backends through Phase 7 (`.github/workflows/ci.yml`): the `test` job runs the
default-Rust backend across CPython 3.12 / 3.13 / 3.14, and `test-python-backend` runs `SASE_CORE_BACKEND=python` on
3.12 / 3.14. The publish workflow's `install-smoke` job installs the built `sase` wheel into a fresh venv and runs
`sase core health` in both backend modes; on failure it dumps `pip list`, Python/platform info, and
`sase_core_rs.__file__` / `__version__` so missing-wheel or ABI-mismatch failures are diagnosable from the build log
without a manual repro.

## Rollback

The Phase 6/7 release cycle keeps the Python implementations in place precisely so the default flip is reversible
without a Rust rebuild. The rollback procedure depends on which phase is active when a problem is reported:

### During Phase 6/7 (Python implementations still ship)

**Per-user immediate mitigation (no release):**

```bash
export SASE_CORE_BACKEND=python   # selects pure-Python; no sase_core_rs required for any shipped operation
sase core health                  # confirms python mode is selected and reports status="ok"
```

This is the documented escape hatch. It works for everything Phase 6 routes through Rust (`parse_project_bytes`,
`parse_query`, `evaluate_query_many`, `scan_agent_artifacts`, `read_status_from_lines`, `apply_status_update`,
`plan_status_transition`, `parse_git_name_status_z`, `parse_git_branch_name`, `derive_git_workspace_name`,
`parse_git_conflicted_files`, `parse_git_local_changes`) and does not require `sase_core_rs` to be importable.

**Project-wide rollback (patch release):**

1. Revert `DEFAULT_BACKEND` in `src/sase/core/backend.py` to `Backend.PYTHON`.
2. Update `tests/test_core_backend.py::test_default_backend_is_rust` (and the matching display/dispatch tests) to assert
   the Python default again. The Phase 6F handoff (`plans/202604/rust_backend_phase6_phase6f_handoff.md`) lists every
   test that paired with the flip; reverting them is the inverse of that change.
3. Update the `## Selecting the Backend at Runtime` table here so `python (default)` reads as the default again.
4. Cut a patch release. The `sase-core-rs` runtime dependency stays declared so `import sase_core_rs` still works for
   anyone who explicitly opts back into Rust with `SASE_CORE_BACKEND=rust`; nothing about the wheel layout or `sase`
   packaging needs to change.
5. Keep `SASE_CORE_DUAL_RUN=1` running in CI so the parity record stays current. Re-enable the flip once the triggering
   regression is fixed.

The Python implementations, dual-run logging, parity gate, and `sase core health` exit codes are all unchanged by the
revert — the rollback is one constant and the matching tests, nothing more.

### After Phase 8 (Python implementations removed)

After Phase 8, the Python implementation halves of the ported operations are deleted, so rollback is a wheel/package fix
rather than a constant flip:

- A Rust-side regression is fixed and re-released as a `sase-core-rs` patch version that `sase` depends on. The pinned
  range is updated in `pyproject.toml` and a `sase` patch release pulls the corrected wheel.
- For an operation where parity drifted before Phase 8 closed, the only safe path is to revert the Phase 8 PR(s) that
  removed the Python halves before the patch release, then redo Phase 7 verification before re-attempting Phase 8.
- The `SASE_CORE_BACKEND=python` env var is removed alongside the Python implementations, so it cannot be used as a user
  mitigation post-Phase 8. This is by design — the env var is a Phase 6/7 release-cycle escape hatch only.

The handoff at `plans/202604/rust_backend_phase6_phase6h_handoff.md` records the exact test list / file list to flip
during the Phase 6/7 rollback path; the Phase 8 entry in `research/202604/rust_backend_migration.md` records what gets
deleted so a future rollback to the pre-Phase 8 layout can be reconstructed from git history.

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
- **Phase 4F** _(complete)_ — Verification, performance decision, and Phase 4 close-out recorded in
  `plans/202604/rust_backend_phase4_status_machine_phase4f_handoff.md`. The Phase 4A benchmark was re-run on the
  refactored implementation under both backends (`bench_status_state_machine_phase4f.json`); the Rust planner adds a
  small wire round-trip cost (~5–7 % on the synthetic 200-spec transition workload) that is invisible at user-perceived
  scales because the orchestrator is dominated by `parse_project_file`, `find_all_changespecs`, and the locked atomic
  write. The dual-run facade was exercised against the golden corpus; 84 `plan_status_transition` records, zero
  mismatches. **Rollout:** `SASE_CORE_BACKEND` stays `python` by default; the Rust planner and line helpers are shipped,
  parity-tested, and **opt-in**. No per-operation default-Rust override is justified — the planner is too cheap to
  motivate a sibling-extension dependency at default install. A circular-import fix in
  `sase/status_state_machine/transitions.py` (deferring `build_status_transition_request` to function scope) was
  required to unbreak top-level `from sase.core.status_facade import …` after the Phase 4E refactor.
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
- **Phase 5B** _(complete)_ — Git query parser facade and wire contract pinned in `src/sase/core/git_query_facade.py`
  and `src/sase/core/git_query_wire.py`. Five pure helpers cover the deterministic parsing and normalization pieces used
  by `GitQueryOpsMixin`: `parse_git_name_status_z`, `parse_git_branch_name`, `derive_git_workspace_name`,
  `parse_git_conflicted_files`, and `parse_git_local_changes`. The wire keeps a single record (`GitNameStatusEntryWire`)
  for the only structured shape; the other helpers return primitive `str | None` / `list[str]` values. Python-only
  golden tests at `tests/test_core_git_query.py` lock down empty/ trailing-NUL streams, simple status letters
  (`A`/`M`/`D`/`T`/`U`), rename/copy entries with scores (`R100`/`C75`) and the legacy `"<old>\t<new>"` paired-path
  encoding, malformed/truncated streams, branch-name detached-HEAD handling, remote URL with/without `.git` and
  SSH-style/path-like remotes, root-path fallback, conflicted-file blank-line stripping, and clean-vs-dirty
  `git status --porcelain` normalization. No production caller is routed through the facade yet — Phase 5C implements
  the Rust pure parsers in `../sase-core` and Phase 5D wires `git_query_facade` into the backend dispatcher.
- **Phase 5C** _(complete)_ — Pure Rust Git query parser module landed in `../sase-core/crates/sase_core/src/git_query/`
  (wire struct + the five pinned parsers) with serde-compatible output and inline + `tests/git_query_parity.rs` cases
  that mirror `tests/test_core_git_query.py` byte-for-byte. PyO3 bindings on `sase_core_rs` expose
  `parse_git_name_status_z` (returning `list[dict]`), `parse_git_branch_name`, `derive_git_workspace_name`,
  `parse_git_conflicted_files`, and `parse_git_local_changes`. No production caller is routed through Rust yet —
  `git_query_facade.py` continues to dispatch every operation to Python.
- **Phase 5D** _(complete)_ — `git_query_facade` registers the five `sase_core_rs` Git query bindings as `rust_impl`
  callbacks whenever the extension is importable. `SASE_CORE_BACKEND=rust` routes every helper through Rust, including
  rehydrating the Rust `parse_git_name_status_z` dict output back into the legacy `list[tuple[str, str]]` shape so call
  sites are backend-independent. Missing bindings under Rust mode raise `RustBackendUnavailableError` (the helpers are
  classified as shipped Rust operations). `SASE_CORE_DUAL_RUN=1` runs both implementations on every dispatched call and
  logs comparison records to `~/.sase/perf/core_dual_run.jsonl`, with the comparison key being the public tuple shape
  for `parse_git_name_status_z` and primitives for the other four. `tests/test_core_git_query.py` adds backend-dispatch
  tests with a fake `sase_core_rs` module (default-Python pass-through, Rust routing, missing-binding
  `RustBackendUnavailableError`, dual-run match + mismatch records) plus a real-extension parity test guarded by
  `pytest.importorskip("sase_core_rs")`. `GitQueryOpsMixin` is intentionally still untouched — Phase 5E swaps the inline
  parsing for facade calls.
- **Phase 5E** _(complete)_ — `GitQueryOpsMixin` (`vcs_diff_name_status`, `vcs_get_branch_name`,
  `vcs_get_workspace_name`, `vcs_get_conflicted_files`, `vcs_has_local_changes`) consumes `sase.core.git_query_facade`
  for every parsing/normalization step. The local `_parse_git_name_status_z` helper is removed; the facade is the single
  source of truth. Public hookimpl shapes are byte-identical: name-status returns `list[tuple[str, str]]` with
  rename/copy entries encoded as `"<old>\t<new>"`; branch and local-changes return `(True, name | None)` with
  `(True, None)` reserved for detached HEAD or clean trees; conflicted files returns `[]` on `git diff` failure;
  workspace name keeps remote-URL priority with the toplevel root as fallback. `tests/perf/ bench_git_query_ops.py` was
  rewritten to import every helper from the facade so the bench reflects the production code path under the active
  backend. The Phase 5E bench artifact (`plans/202604/perf_artifacts/bench_git_query_ops_phase5e.json`) records
  Python-facade, Rust-facade, and dual-run numbers across `synthetic_small`/`_medium`/`_large` and
  `end_to_end_50`/`_500` workloads.
- **Phase 5F** _(complete)_ — Verification pass, parity sweep, and Phase 5 close-out recorded in
  `plans/202604/rust_backend_phase5_git_query_ops_phase5f_handoff.md`. Re-ran the focused tests under default Python,
  `SASE_CORE_BACKEND=rust`, and `SASE_CORE_DUAL_RUN=1` (75 passed in each mode); `just rust-check` and `just check` both
  green. Dual-run log shows 3460 Git-query records across the five helpers with **0 mismatches** combined with the prior
  parity logs for parser, query, agent scan, and status planner. **Rollout:** `SASE_CORE_BACKEND` stays `python` by
  default; the Rust Git query parsers are shipped, parity-tested, and **opt-in**. Phase 5 evidence is consistent with
  Phase 5A: subprocess fork+exec dominates end-to-end Git query cost so the Rust parser is neutral end-to-end on every
  measured workload. The shared-core hygiene goal is met — the parsers now live in the Rust crate and are exercised by
  both Python tests and `tests/git_query_parity.rs`. No per-operation default-Rust override is justified; Phase 6
  default-flip prerequisites (wheel build, packaging story, CI dual-run on the golden corpus) are unchanged. Rollback
  path: Python helpers remain as `*_python` exports in `git_query_facade`; setting `SASE_CORE_BACKEND=python` (the
  default) restores the pure-Python path with no provider-side change.
- **Phase 6A** _(complete)_ — `sase-core-rs` packaging and release matrix landed in `../sase-core`.
  `crates/sase_core_py` ships a maturin-managed Python distribution (`sase-core-rs`, import module `sase_core_rs`) with
  `abi3-py312` so a single wheel per platform-architecture covers CPython 3.12 / 3.13 / 3.14. The release workflow
  builds Linux x86_64, Linux aarch64, macOS universal2, and Windows x86_64 wheels plus an sdist on tag push, runs
  per-runner import + parser smoke (`parse_query("status:Ready")` plus a `parse_query("(")` negative case), and
  publishes to PyPI when a `vX.Y.Z` tag is pushed. Free-threaded CPython (`3.13t` / `3.14t`) is intentionally out of
  scope for this release.
- **Phase 6B** _(complete)_ — `sase` declares `sase-core-rs>=0.1.0,<0.2.0` as a runtime dependency, so a normal
  `pip install sase` or `uv tool install sase` resolves the prebuilt Rust extension wheel from PyPI; no Rust toolchain
  is required for users. `just install` auto-runs `just rust-install` first when a sibling `../sase-core` checkout and a
  `cargo` toolchain are both available, so editable source dev satisfies the new dependency from local Rust without
  round-tripping through PyPI. The publish workflow runs an install-smoke that imports `sase_core_rs` and exercises a
  shipped binding in a fresh venv before PyPI upload, and a CI install-smoke job mirrors the same checks on every PR.
  `SASE_CORE_BACKEND=python` remains a runtime escape hatch that does not require `sase_core_rs` to be importable. The
  default backend is **still Python**; the flip is Phase 6F.
- **Phase 6C** _(complete)_ — Backend contract audit and fallback tests. Every `dispatch(...)` call site under
  `src/sase/core/` is classified as **shipped** (12 operations, missing binding raises `RustBackendUnavailableError`) or
  **unported** (5 operations, Python via `rust_unavailable="python"`). `tests/test_core_facade/test_backend_contract.py`
  enumerates both sets, verifies the dispatcher's contract end-to-end, pins the dual-run no-op semantics for operations
  without a `rust_impl`, and fails if a new `dispatch(operation=...)` call site is added without explicit
  classification. The `RustBackendUnavailableError` text now names the operation, the `sase_core_rs` extension module,
  and the `SASE_CORE_BACKEND=python` escape hatch. The default backend is **still Python**; the flip is Phase 6F.
- **Phase 6D** _(complete)_ — Backend health check and user-facing diagnostics.
  `sase.core.health.check_backend_health()` resolves the selected backend, attempts to import `sase_core_rs`, calls a
  cheap shipped binding (`parse_query("status:Ready")`) when the extension is loaded, and returns a frozen
  `BackendHealthReport` with module path / version / Python version / platform / probe result / explicit error fields.
  The new `sase core health` CLI (`-j` / `--json` for machine output) prints the report and exits non-zero whenever the
  report is `status="error"`, giving release smokes a single contracted command for "is the Rust core active and
  healthy?". Default Rust with a missing or misbuilt `sase_core_rs` exits non-zero; explicit `SASE_CORE_BACKEND=python`
  succeeds without requiring the extension; non-`ImportError` import failures are surfaced verbatim rather than silently
  swallowed. The CI install-smoke job (`.github/workflows/ci.yml`) and the release install-smoke job
  (`.github/workflows/publish.yml`) both invoke `sase core health` (default + `SASE_CORE_BACKEND=python` runs) instead
  of inline import / binding probes. The default backend is **still Python**; the flip is Phase 6F.
- **Phase 6E** _(complete)_ — `is_workflow_complete` regression resolution. Phase 3D had routed
  `sase.agent.names._lookup.is_workflow_complete` through the snapshot facade, which turned the predicate into a
  full-tree scan even though the predicate only needs artifacts whose `workflow_name` matches the queried name. Phase 6E
  pins the function to a targeted Python traversal that walks `~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json`
  directly and only opens marker files for the matching workflow, regardless of `SASE_CORE_BACKEND`. `find_named_agent`
  keeps the snapshot path because it consumes the snapshot data more broadly. A new regression test
  (`tests/test_agent_names_workflow.py::test_backend_does_not_route_through_snapshot`) asserts the targeted path is in
  effect under each backend selection by patching `scan_agent_artifacts` to raise. The Phase 6E micro-benchmark
  (`tests/perf/bench_workflow_complete.py`, 6×200 synthetic workload, 10 workflows, target = `wf_0`) records the new
  numbers:

  | Backend mode | `is_workflow_complete` (Phase 6E) | snapshot-then-filter (pre-6E shape) |
  | ------------ | --------------------------------: | ----------------------------------: |
  | python       |                             34 ms |                              102 ms |
  | rust         |                             34 ms |                               88 ms |
  | dual_run     |                             33 ms |                              188 ms |

  The targeted path is ~3× faster than the previous Python snapshot-backed path, ~2.6× faster than the Rust
  snapshot-backed path, and immune to the dual-run amplification that doubled the snapshot cost. The default backend is
  **still Python**; the flip is Phase 6F. A Rust early-exit binding for this predicate was considered and rejected: the
  targeted Python path already eliminates the regression and the predicate runs against a tree that is rarely large
  enough to benefit from a PyO3 boundary crossing.

- **Phase 6F** _(complete)_ — Default backend flipped to Rust. `DEFAULT_BACKEND` is now `Backend.RUST`, so an unset
  `SASE_CORE_BACKEND` selects Rust; explicit `SASE_CORE_BACKEND=python` remains the documented escape hatch through
  Phase 7. `RustBackendUnavailableError` is now the surface for shipped operations whose binding is missing under the
  default — there is no silent fallback. The TUI backend indicator, `sase core health` exit codes, and the dual-run
  semantics from Phase 6C–6E carry over unchanged: dual-run still returns the Python result;
  `transition_changespec_status` and the other unported facade operations still route to Python via
  `rust_unavailable="python"`. Tests that previously asserted "default Python" semantics now either assert "default
  Rust" (e.g. `test_default_backend_is_rust`) or pin themselves to explicit Python where the test is exercising the
  pure-Python implementation. `is_workflow_complete` remains on its targeted Python traversal (Phase 6E pin) regardless
  of backend selection. Rollback is a single-line change: revert `DEFAULT_BACKEND` to `Backend.PYTHON` and ship a patch
  release; the Python implementations are unchanged and dual-run logging continues to provide parity coverage in the
  meantime.
- **Phase 6G** _(complete)_ — CI matrix, parity gate, and release smoke. `.github/workflows/ci.yml` now runs the full
  pytest suite on both backends through Phase 7: the `test` job runs default-Rust across CPython 3.12 / 3.13 / 3.14, and
  `test-python-backend` runs `SASE_CORE_BACKEND=python` on 3.12 / 3.14. A new `parity-gate` job runs
  `tests/parity/dual_run_parity.py` against the golden corpus and the sanitized synthetic home-tree fixture
  (`tests/agent_scan_golden/fixture_builder`) under `SASE_CORE_DUAL_RUN=1`, fails on any mismatch for non-divergent
  shipped operations, and uploads `parity-artifacts/` (JSONL log + JSON summary) for post-hoc inspection. The
  `parse_project_bytes` documented divergence (Phase 1F end-line gap) is allow-listed in `DOCUMENTED_DIVERGENCE` and
  pinned by `tests/test_core_parity_smoke.py`. `publish.yml`'s `install-smoke` job adds an `if: failure()` diagnostic
  step that re-runs the health checks, dumps `pip list`, Python/platform info, and `sase_core_rs.__file__` /
  `__version__` so missing-wheel and ABI-mismatch failures are diagnosable from the build log alone. Local mirror:
  `just parity-check`. See `plans/202604/rust_backend_phase6_phase6g_handoff.md`.
- **Phase 6H** _(complete)_ — Documentation, rollback plan, and Phase 6 close-out. `docs/rust_backend.md` is restated in
  the production-default voice (this page) with explicit `Verifying The Backend` and `Rollback` sections covering both
  the Phase 6/7 reversible path and the post-Phase 8 wheel-fix path. `research/202604/rust_backend_migration.md` is
  updated to mark Phase 6 complete, record the packaging decision (`sase-core-rs` as a separate PyPI distribution;
  `sase` declares it as a runtime dependency), the CI matrix shape (default-Rust 3.12/3.13/3.14 plus explicit-Python
  3.12/3.14 + `parity-gate` + `install-smoke`), and the `is_workflow_complete` Phase 6E pin (targeted Python traversal,
  ~3× faster than the snapshot path, no Rust early-exit binding required). Phase 7 (measurement and benchmark gate) is
  restated as the immediate next track. See `plans/202604/rust_backend_phase6_phase6h_handoff.md`.
- **Phase 7** _(complete)_ — Measurement and benchmark-floor pass. After the default flip, before the Python
  implementations are removed, every shipped Rust-backed core operation and the three end-to-end CLI/TUI surfaces were
  measured under explicit Python and default Rust; the user-facing tables and support note live above in `Performance`,
  the research-side analysis in `research/202604/rust_backend_phase7_performance.md`. The CI regression floor is now
  wired through `tests/perf/baselines/phase7_regression_floor.json`, `tests/perf/phase7_check_regression.py`, and the
  `phase7-perf-floor` GitHub Actions job (invoked by `just phase7-perf-check`); the JSON floor-check report is uploaded
  on every run. **Subphase status:** 7A (measurement contract), 7B (core operation microbenchmarks), 7C (end-to-end
  TUI/CLI measurements), 7D (this document's `Performance` section + research narrative), 7E (CI regression floor), and
  7F (verification close-out) are all complete. The committed Phase 7 artifacts live under
  `plans/202604/perf_artifacts/`; per-subphase handoffs live next to the plan as
  `plans/202604/rust_backend_phase7_phase7{a,b,c,d,e,f}_handoff.md`.
- **Future phases** — Additional facade operations (graph index, agent-status state machine) become candidates for Rust
  re-implementation as they show up in profiles. Re-evaluate streaming only if a workload appears where Rust scan time
  is small but Python adaptation dominates. `gix` remains out of scope for the Git query surface unless a future profile
  shows a hot caller invoking these helpers in a tight loop.

The migration strategy intentionally keeps the Rust core as a single crate that can be exposed through three different
binding layers: PyO3 for the TUI/CLI (today), uniffi for mobile, and wasm for the web. See
`research/202604/rust_backend_migration.md` for the broader plan.
