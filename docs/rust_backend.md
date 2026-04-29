# Optional Rust Backend (`sase_core_rs`)

A subset of sase's core APIs (currently `parse_project_bytes`) can be served by an optional Rust extension built from a
sibling [`sase-core`](https://github.com/sase-org/sase-core) repo. The Rust backend is **opt-in**: pure-Python installs
keep working with no Rust toolchain, and every `just rust-*` target degrades to a friendly no-op when the sibling repo
is absent.

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

| Module                  | Purpose                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------ |
| `backend.py`            | `SASE_CORE_BACKEND` dispatcher; `is_rust_available()`; `RustBackendUnavailableError` |
| `parser_facade.py`      | `parse_project_file` / `parse_project_bytes` — the first dispatched operation        |
| `wire.py`               | Stable wire record types that cross the Python ↔ Rust boundary                       |
| `wire_conversion.py`    | Python `ChangeSpec` ↔ wire record serialization                                      |
| `dual_run.py`           | Optional Python+Rust comparison logging (`SASE_CORE_DUAL_RUN=1`)                     |
| `query_facade.py`       | Query parse / build / evaluate facade                                                |
| `status_facade.py`      | Status transition helpers facade                                                     |
| `graph_index_facade.py` | `build_changespec_graph_index()` facade                                              |
| `agent_scan_facade.py`  | `scan_agent_artifacts()` snapshot facade (Phase 3)                                   |
| `agent_scan_wire.py`    | Stable wire records for the agent-artifact scan snapshot                             |

The Rust extension is a sibling repo at `../sase-core/`, organized as a Cargo workspace with a PyO3 crate at
`crates/sase_core_py/`.

## Installing the Rust Backend

Rust dev tools are required: install [rustup](https://rustup.rs/) so `cargo` is on `PATH`. Then clone the Rust core
beside this repo and build the PyO3 extension into the active venv:

```bash
git clone https://github.com/sase-org/sase-core.git ../sase-core
just rust-install   # builds + installs sase_core_rs via maturin develop --release
```

`just rust-install` installs `maturin` into `.venv` on demand and runs `maturin develop --release` inside
`../sase-core/crates/sase_core_py/`. After it succeeds, `python -c "import sase_core_rs"` works inside the venv.

## Selecting the Backend at Runtime

| Env var              | Values                     | Effect                                                                                                                                                       |
| -------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SASE_CORE_BACKEND`  | `python` (default), `rust` | Selects which implementation each dispatched operation uses                                                                                                  |
| `SASE_CORE_DUAL_RUN` | `1` / `true` / `yes`       | Run both impls on every dispatched op; log mismatches to `~/.sase/perf/core_dual_run.jsonl`. The Python result is always returned while dual-run is enabled. |

Selecting `SASE_CORE_BACKEND=rust` when `sase_core_rs` is not importable raises `RustBackendUnavailableError` rather
than silently falling back — this is intentional, so a missing wheel cannot quietly mask a regression in production.

`is_rust_available()` is a lazy, forgiving probe: an `ImportError` simply reports `False` so a pure-Python install is
never broken; other import-time failures propagate so a _misbuilt_ wheel surfaces immediately.

`parse_project_file()` stays Python-only even when Rust is available — the Rust binding consumes bytes, and re-reading
the file from disk would defeat the perf rationale. Callers that want the Rust path read the file themselves and call
`parse_project_bytes()`.

## Justfile Targets

Each target prints a friendly skip message when `../sase-core` is absent and exits 0, so pure-Python contributors are
never blocked.

| Target                  | Description                                                                                  |
| ----------------------- | -------------------------------------------------------------------------------------------- |
| `just rust-install`     | Build + install `sase_core_rs` via `maturin develop --release` (installs maturin if missing) |
| `just rust-test`        | `cargo test --workspace` in `../sase-core`                                                   |
| `just rust-fmt`         | Auto-format Rust sources with `cargo fmt --all`                                              |
| `just rust-fmt-check`   | CI-mode formatting verification (`cargo fmt --all -- --check`)                               |
| `just rust-clippy`      | `cargo clippy --workspace --all-targets -- -D warnings`                                      |
| `just rust-check`       | Combined Rust check: `rust-fmt-check` + `rust-clippy` + `rust-test`                          |
| `just rust-bench`       | Run the direct-parser Rust benchmark (`cargo run --release --example bench_parse`)           |
| `just bench-core`       | Python `parse_project_bytes` benchmark across all available backends                         |
| `just bench-agent-scan` | Python agent-artifact scan benchmark vs current direct loaders (Phase 3 baseline)            |

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
- **Future phases** — Additional facade operations (graph index, status helpers) become candidates for Rust
  re-implementation as they show up in profiles.

The migration strategy intentionally keeps the Rust core as a single crate that can be exposed through three different
binding layers: PyO3 for the TUI/CLI (today), uniffi for mobile, and wasm for the web. See
`research/202604/rust_backend_migration.md` for the broader plan.
