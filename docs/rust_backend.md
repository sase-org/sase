# Rust Backend (`sase_core_rs`)

A subset of sase's core APIs is served by a Rust extension distributed as
[`sase-core-rs`](https://pypi.org/project/sase-core-rs/) on PyPI and built from the sibling
[`sase-core`](https://github.com/sase-org/sase-core) repo. `sase` declares `sase-core-rs>=0.1.1,<0.2.0` as a hard
runtime dependency, so a normal `pip install sase` (or `uv tool install sase`) on a supported platform pulls a prebuilt
wheel automatically — no Rust toolchain required, no env-var selection, no Python fallback for ported operations.

The shipped Rust-backed operations are:

- `parse_project_bytes`
- `parse_query`
- `scan_agent_artifacts`
- `read_status_from_lines`
- `apply_status_update`
- `plan_status_transition`
- `parse_git_name_status_z`
- `parse_git_branch_name`
- `derive_git_workspace_name`
- `parse_git_conflicted_files`
- `parse_git_local_changes`
- persistent query corpus handles (`compile_corpus`, `compile_query`, `evaluate_many`) used by
  `sase.core.query_corpus_facade`
- notification JSONL store operations (`read_notifications_snapshot`, `append_notification`,
  `apply_notification_state_update`, `rewrite_notifications`) used by `sase.core.notification_store_facade`
- `plan_agent_cleanup`
- agent cleanup execution helpers for dismissed indexes/bundles, artifact deletion, workspace release text mutation, and
  hook/mentor/comment kill marking
- Rust-backed agent launch helpers:
  - `allocate_launch_timestamp_batch`
  - `prepare_agent_launch`
  - `spawn_prepared_agent_process`
  - `plan_agent_launch_fanout`
- Rust-backed bead operations:
  - read queries (`show`, `list`, `ready`, `blocked`, `stats`, `doctor`, epic-child lookups)
  - merged multi-workspace read queries
  - mutations (`init`, `create`, `update`, `open`, `close`, `rm`, `dep add`, ready-to-work flags, JSONL export)
  - deterministic epic work DAG planning
  - the early `sase bead` CLI fast path for common read/write commands

The intentionally Python-owned facade surfaces (host logic, not backend fallbacks) are:

- `parse_project_file` — Python file-path API. The Rust binding consumes bytes; routing the file-path API through it
  would either re-read the file or duplicate the Python parser's tokenization for no measurable win.
- `build_query_context`, `evaluate_query`, `evaluate_query_with_context` — per-row query host logic. Batch product
  filtering uses a cached Rust query corpus; the public `evaluate_query_many(query, changespecs)` API remains as a
  compatibility wrapper that compiles a temporary Rust corpus for one call.
- `build_changespec_graph_index` — ChangeSpec graph index construction.
- `transition_changespec_status` — the side-effecting status transition (acquires a file lock, rewrites the project
  file, performs archive moves and suffix renames). The pure decision step inside it routes through Rust via
  `plan_status_transition`.
- High-level subprocess orchestration, process liveness checks outside launch, filesystem mutation outside the prepared
  prompt/output path, TUI rendering, and plugin entry points stay on the host by design.
- Agent launch host responsibilities stay in Python: provider/workspace plugin calls, VCS preallocation env mapping,
  project-file locking, workspace-directory cleanup, TUI notifications, xprompt catalog expansion, history writes, chop
  registry recording, and user-facing launch callbacks. Rust owns deterministic launch planning/preparation and the
  low-level detached spawn binding.
- Agent cleanup process signalling and TUI orchestration stay on the host. The Rust boundary owns reusable planning,
  deterministic dismissed-agent data mutations, artifact deletion, workspace-release content rewrites, and
  ChangeSpec-entry kill marking exposed through Python helpers in `sase.core.agent_cleanup_*`.
- Bead host responsibilities stay in Python where they touch the surrounding application: storage-location discovery,
  SASE workspace/project lookup, VCS prompt context for `sase bead work`, xprompt resolution, user confirmation, agent
  launch, rollback of already-spawned children, and telemetry increments. Rust owns the bead data model, storage/query
  engine, JSONL codecs, mutation transactions, workspace merge, deterministic work-plan DAG, and CLI output planning.

## Why a Rust Backend?

The `sase.core` package is a stable Python facade carved out specifically so individual operations can be re-served by
faster Rust implementations one at a time. Parsing project `.gp` files dominates many cold-path workloads (TUI startup,
large search results, axe lumberjack scans), so it was the first operation routed through this seam.

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
                │  agent_scan_facade · git_query_facade       │
                └────────────┬───────────────────┬────────────┘
                             │                   │
                ported facades                unported facades
                             │                   │
                             ▼                   ▼
                ┌──────────────────────┐   ┌──────────────────┐
                │  sase_core_rs (PyO3) │   │  Python impl     │
                │  required extension  │   │  (host logic)    │
                └──────────────────────┘   └──────────────────┘
```

The facade lives at `src/sase/core/`:

| Module                         | Purpose                                                                                                            |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `rust.py`                      | Strict `sase_core_rs` loader (`require_rust_extension`, `require_rust_binding`)                                    |
| `health.py`                    | `sase core health` Rust-extension probe + report                                                                   |
| `parser_facade.py`             | `parse_project_file` Python API + Rust-backed `parse_project_bytes`                                                |
| `wire.py`                      | Stable wire record types that cross the Python ↔ Rust boundary                                                     |
| `wire_conversion.py`           | Python `ChangeSpec` ↔ wire record serialization                                                                    |
| `query_facade.py`              | `parse_query` (Rust); per-row query context/eval (Python host logic); batch compatibility wrapper over Rust corpus |
| `query_corpus_facade.py`       | Persistent Rust query corpus wrapper for cached batch evaluation                                                   |
| `notification_store_facade.py` | Notification JSONL snapshot, append, rewrite, and state mutation facade (Rust)                                     |
| `notification_store_wire.py`   | Stable notification snapshot/update wire records across the Rust boundary                                          |
| `status_facade.py`             | Status line helpers + planner (Rust); side-effecting transition (Python host logic)                                |
| `graph_index_facade.py`        | `build_changespec_graph_index()` facade (Python host logic)                                                        |
| `agent_scan_facade.py`         | `scan_agent_artifacts()` snapshot facade (Rust)                                                                    |
| `agent_scan_wire.py`           | Stable wire records for the agent-artifact scan snapshot                                                           |
| `agent_cleanup_wire.py`        | Stable cleanup planning and side-effect intent wires                                                               |
| `agent_cleanup_facade.py`      | Agent cleanup target conversion and `plan_agent_cleanup()` facade                                                  |
| `agent_cleanup_execution.py`   | Host-safe wrappers for Rust-backed deterministic cleanup mutations                                                 |
| `agent_launch_wire.py`         | Stable launch, workspace-claim, and fan-out wire records                                                           |
| `agent_launch_facade.py`       | Rust-backed launch preparation, spawn, timestamp allocation, and fan-out planning                                  |
| `agent_launch_claims.py`       | Rust-backed RUNNING-field claim planning/mutation helpers                                                          |
| `bead_read_facade.py`          | Rust-backed bead read and merged-workspace read facade                                                             |
| `bead_mutation_facade.py`      | Rust-backed bead mutation facade                                                                                   |
| `bead_wire.py`                 | Stable bead issue/dependency conversion helpers across the Rust boundary                                           |
| `status_wire.py`               | Stable wire records for the status state machine                                                                   |
| `status_wire_conversion.py`    | Python plan reference + project-file → request-wire converter                                                      |
| `git_query_facade.py`          | Pure Git query parsers facade (Rust)                                                                               |
| `git_query_wire.py`            | Stable wire records for the Git query parsers                                                                      |

The Rust extension is a sibling repo at `../sase-core/`, organized as a Cargo workspace with a PyO3 crate at
`crates/sase_core_py/`.

## Bead Backend

The `sase bead` migration is tracked by `sdd/epics/202605/bead_rust_backend_migration.md`. The shipped path is now
Rust-owned for data operations: JSONL/config parsing, SQLite rebuild/query, mutations, workspace merge, deterministic
epic work planning, and common CLI output planning all live in `sase-core` and are exposed through `sase_core_rs`.
Python remains the host layer for path discovery, VCS context, xprompt lookup, confirmation prompts, launch/rollback,
and telemetry side effects.

Golden contract fixtures live under `tests/test_bead/golden/`:

- `cli/` pins stdout/stderr for `init`, `create`, `list`, `show`, `ready`, `blocked`, `stats`, `dep add`, `update`,
  `open`, `close`, `rm`, `sync --status`, and representative error paths.
- `jsonl/` pins current and legacy JSONL shapes, corrupt-line tolerance, empty/missing import behavior, hierarchy,
  dependencies, cross-epic blockers, and ChangeSpec metadata.
- `stores/current/` is a complete deterministic bead store used by the CLI golden tests.

Run the focused contract tests with:

```bash
pytest tests/test_bead/test_cli_golden.py tests/test_bead/test_jsonl_golden_fixtures.py
```

The reproducible bead benchmark harness is:

```bash
python tests/perf/bench_bead.py --runs 5 --output /tmp/bead-bench.json
python tests/perf/bench_bead.py --runs 5 --issues 10000 --dependencies 20000 --output /tmp/bead-bench-large.json
```

By default the shell measurements run `python -m sase.main.entry`; pass `--sase-bin "$(command -v sase)"` to measure an
installed console script. The harness reports JSON summaries for:

- shell command latency for `sase bead list`, `ready`, and `show`;
- direct Python `BeadProject` reads;
- merged workspace reads across three bead stores;
- synthetic stores sized by `--issues` and `--dependencies`.

The Phase A local baseline on the then-active 399-line store was approximately:

| Command / action            | Baseline |
| --------------------------- | -------- |
| `sase bead list`            | 0.32s    |
| `sase bead ready`           | 0.34s    |
| `sase bead show <id>`       | 0.36s    |
| Plain Python startup        | 0.08s    |
| Importing `sase.main.entry` | 0.23s    |
| Importing `sase_core_rs`    | 0.02s    |

Post-migration targets for bead checks and future regression floors:

- `sase bead list`, `ready`, and `show` on the current-size store: p50 under 120ms from shell command start.
- Direct Rust read bindings after Python startup: p50 under 10ms.
- Large synthetic store, 10k issues / 20k dependencies: direct Rust read queries under 50ms p50, merged workspace reads
  under 100ms p50 for three stores, and write plus JSONL export under 150ms p50.
- No drift in the Phase A golden CLI output unless the migration plan records an intentional compatibility change.

## Installing the Rust Backend

### Released `sase` (recommended for users)

`sase-core-rs` is a regular runtime dependency of `sase`. A standard install pulls a prebuilt wheel for the host
platform from PyPI; no Rust toolchain is needed:

```bash
pip install sase
# or
uv tool install sase
```

The release matrix ships wheels for CPython 3.12+ on Linux x86_64, Linux aarch64, macOS universal2, and Windows x86_64.
After install, `python -c "import sase_core_rs"` succeeds inside the same venv that runs `sase`.

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
just rust-install                 # repo .venv (used by `just test`, benchmarks)
just rust-install-uv-tool         # $(uv tool dir)/sase
just rust-install /path/to/venv   # any other venv (pipx, system Python, custom location)
```

Both targets install `maturin` into the target venv on demand and run `maturin develop --release` inside
`../sase-core/crates/sase_core_py/`, so re-running them after a `../sase-core` update is the supported way to refresh an
existing source install.

### No pure-Python fallback

A working `sase` install requires a loadable `sase_core_rs` extension. There is no `SASE_CORE_BACKEND` env var, no
Python escape hatch for ported operations, and no silent fallback when the wheel is missing. A misbuilt or absent
extension fails fast: ported facades raise `ImportError` from `sase.core.rust.require_rust_extension`, or
`AttributeError` from `require_rust_binding` when the wheel is too old to expose the requested binding.
`sase core health` exits non-zero in either case.

If a contributor's local checkout does not have a working `sase_core_rs`, the fix is to run `just install` (or
`just rust-install` against a sibling `../sase-core/`) — not to disable Rust.

## Backend Health Check

`sase core health` is the scriptable answer to "is the Rust extension loadable and working?". It imports `sase_core_rs`,
calls cheap parser, launch, and bead probes (`parse_query("status:Ready")`, `agent_launch_wire_schema_version()`,
`plan_agent_launch_fanout(...)`, and a temporary-store `bead_cli_execute(["show", ...])`), and reports module path /
version / Python version / platform tag in one block. Two output modes:

```bash
sase core health        # human-readable, line-oriented
sase core health -j     # machine-readable JSON (alias: --json)
```

Exit codes:

| Extension state                                 | `status` | Exit |
| ----------------------------------------------- | -------- | ---- |
| importable, parser + launch + bead probes work  | `ok`     | 0    |
| missing or misbuilt                             | `error`  | 1    |
| importable but a parser/launch/bead probe fails | `error`  | 1    |
| importable but missing a representative binding | `error`  | 1    |

A misbuilt wheel that fails to import with a non-`ImportError` is surfaced verbatim in the `error` / `error_kind` fields
rather than silently masked.

Release jobs and CI install-smokes call `sase core health` instead of probing `import sase_core_rs` and a binding by
hand: it is the same check, but its exit code is the contract.

## Justfile Targets

Each target prints a friendly skip message when `../sase-core` is absent and exits 0, so contributors without the
sibling checkout are never blocked.

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
| `just bench-core`           | Python `parse_project_bytes` benchmark (Rust-direct + facade rows)                                          |
| `just bead-perf-smoke`      | Tiny `sase bead` shell/facade/work-plan benchmark used as the CI smoke artifact                             |
| `just bench-agent-scan`     | Python agent-artifact scan benchmark vs current direct loaders                                              |
| `just bench-agent-launch`   | Fake-spawn launch benchmark through the Rust preparation binding                                            |
| `just launch-perf-check`    | CI-friendly launch regression check against the Phase 1 fan-out baseline                                    |
| `just phase7-perf-check`    | Run the Phase 7 regression-floor checker against the recorded Rust ceilings                                 |

## Performance

Phase 7 captured a deliberate measurement pass after the Rust default flip; Phase 8 then deleted the Python halves of
the ported operations, so the historical Python comparisons are frozen evidence rather than live measurements. The raw
JSON artifacts live under `sdd/plans/202604/perf_artifacts/`; the tables below summarize the medians a reader should
expect when running the same harnesses against the same Rust extension.

### Workstation profile

All numbers below come from a single capture machine (Phase 7B + 7C, 2026-04-29):

- Linux x86_64, CPython 3.14.3.
- `sase-core-rs` editable install built from a sibling `../sase-core/` checkout via `just rust-install`; metadata in
  every artifact's `metadata.rust_module_path` / `metadata.rust_module_version` records the exact extension probed.
- Sample sizes per scenario are recorded inline below and pinned in each artifact's `metadata.runs` / `metadata.warmup`.
  End-to-end TUI/CLI runs are 10–12 samples; microbenchmarks are 20–200 samples per scenario.

The historical `python_median` columns are preserved as Phase 7B baselines — they are no longer reproducible from a
post-Phase 8 install (the Python halves are gone) but remain useful for understanding why each operation was kept on
Rust. `speedup` reads `python_median / rust_median` against those frozen Python numbers.

### Core operations (Phase 7B microbenchmarks)

Driver: `tests/perf/phase7/run_phase7b.py`. One `*_summary.json` artifact per shipped operation under
`sdd/plans/202604/perf_artifacts/rust_backend_phase7_<op>_summary.json`; each artifact embeds the Phase 7A
`Phase7Metadata` envelope, the relevant scenario summaries, and pre-computed `(workload, scenario)` comparison rows.

| Operation                    | Workload                 | Scenario                   | py median (Phase 7B) | rust median |   speedup |
| ---------------------------- | ------------------------ | -------------------------- | -------------------: | ----------: | --------: |
| `parse_project_bytes`        | golden_myproj            | facade                     |               296 µs |      124 µs |  **2.4×** |
| `parse_project_bytes`        | synthetic_200_specs      | facade                     |              26.7 ms |     19.1 ms |  **1.4×** |
| `parse_query`                | parse_only               | direct                     |              12.3 µs |      5.8 µs |  **2.1×** |
| `scan_agent_artifacts`       | synthetic_6p_200pp       | scan_facade                |               145 ms |      120 ms | **1.21×** |
| `read_status_from_lines`     | synthetic_200_specs_pure | read_status_from_lines     |               182 µs |      349 µs |     0.52× |
| `apply_status_update`        | synthetic_200_specs_pure | apply_status_update        |               256 µs |      377 µs |     0.68× |
| `plan_status_transition`     | synthetic_200_specs_pure | plan_status_transition     |              8.66 µs |    18.78 µs |     0.46× |
| `parse_git_name_status_z`    | synthetic_medium (1k)    | parse_git_name_status_z    |               626 µs |      880 µs |     0.71× |
| `parse_git_branch_name`      | normalizers_x4           | parse_git_branch_name      |              8.74 µs |    10.40 µs |     0.84× |
| `derive_git_workspace_name`  | normalizers_x5           | derive_git_workspace_name  |              11.7 µs |     13.5 µs |     0.87× |
| `parse_git_conflicted_files` | normalizers_50_lines     | parse_git_conflicted_files |              5.35 µs |     6.83 µs |     0.78× |
| `parse_git_local_changes`    | normalizers_150_entries  | parse_git_local_changes    |              4.51 µs |     5.68 µs |     0.79× |

The historical one-shot Rust `evaluate_query_many(query, dicts)` binding remains a non-product diagnostic row only. The
shipped product route uses a persistent Rust query corpus: compile `ChangeSpec` wire records once per stable list
object, then compile/evaluate each query string against that cached corpus. Query-corpus Phase 6 measured the product
query-keystroke path at 37-74x faster than the Python batch reference on the synthetic workloads and added the
`synthetic_1000_specs` persistent query-keystroke row to the regression floor.

The full per-percentile data (min / median / p95 / max) is in each artifact's `workloads[].baseline` /
`workloads[].candidate`; the `comparisons[]` rows pre-compute `ratio`, `speedup`, and `percent_delta` for every
`(workload, scenario)` pair.

### End-to-end TUI / CLI surfaces (Phase 7C)

Driver: `tests/perf/bench_phase7_e2e.py`. One artifact per `(surface, backend)` invocation under
`sdd/plans/202604/perf_artifacts/rust_backend_phase7_<surface>_<backend>.json`; the home-tree `sase agents status` rows
sit in the gitignored `sdd/plans/202604/perf_artifacts/local_only/` dir because they reflect a workstation-specific
tree.

| Surface                      | Workload                          | runs |     rust | python (Phase 7B) |   speedup |
| ---------------------------- | --------------------------------- | ---- | -------: | ----------------: | --------: |
| `sase_run_startup`           | `import_run_query_cold`           | 12   | 249.3 ms |          252.6 ms |     1.01× |
| `sase_agents_status_listing` | `synthetic_8_projects_25_agents`  | 12   | 298.5 ms |          774.5 ms | **2.59×** |
| `sase_agents_status_listing` | `home_tree` (local-only artifact) | 5    | 885.8 ms |        1,799.7 ms | **2.03×** |
| `sase_ace_cold_open`         | `synthetic_100_cs_50_agents`      | 10   | 1,472 ms |          1,237 ms |     0.84× |

`sase_run_startup` measures cold subprocess `python -c "from sase.main.query_handler._query import run_query"`; it
deliberately stops at the dispatcher's provider boundary, never resolves a provider, never touches the network, and
never claims a workspace. The `metadata.extra.boundary` field in the artifact records this scope so a future agent can
push the boundary further toward provider resolution without invalidating the comparison.

### Agent launch migration (Phase 9)

Driver: `tests/perf/bench_agent_launch.py`; regression check: `tests/perf/check_agent_launch_regression.py`. The harness
uses temp ProjectSpec files and fake subprocess writes so it never starts an LLM CLI, but it now runs launch preparation
through the production Rust binding. The committed Phase 1 baseline is
`sdd/plans/202605/perf_artifacts/agent_launch_phase1_baseline.json`.

The Phase 1 baseline intentionally includes parent-side fan-out sleeps: three-way `%model` and `%r` launches each spent
about 2,001 ms in the parent before the migration. `just launch-perf-check` runs the current harness without those
sleeps and fails if `model_fanout` or `repeat_fanout` exceeds 25% of the Phase 1 median. Single-prompt, VCS, and
deferred-workspace fake launches also have a generous 100 ms median ceiling so the gate catches accidental blocking work
without depending on a specific workstation's sub-millisecond numbers.

### Where Rust helps, where it does not

**Wins:**

- `sase agents status -j` cold listing is the headline Rust win — ~2.6× on the synthetic 8×25 tree and ~2.0× on this
  workstation's home tree. The cold subprocess wall-time is dominated by `scan_agent_artifacts`, which Rust ports.
- `parse_project_bytes` is a clean ~2.4× win on small files and ~1.4× on a 200-spec synthetic file.
- `parse_query` direct parsing is a ~2.1× win on the parse-only workload.

**Honest negatives (kept on Rust for shared-core hygiene rather than user-perceived latency):**

- The status-line helpers (`read_status_from_lines`, `apply_status_update`, `plan_status_transition`) and the small Git
  normalizers (`parse_git_branch_name`, `derive_git_workspace_name`, `parse_git_conflicted_files`,
  `parse_git_local_changes`) are 13–55% slower under Rust than the historical Python implementations on the inputs they
  actually see in production. These are dispatch-overhead-dominated cores at sub-10-µs absolute cost; the gap is
  single-digit microseconds and is invisible against the surrounding subprocess / atomic-write cost.
- `parse_git_name_status_z` is consistently ~25–30% slower than the historical Python on synthetic streams, but the
  end-to-end `git diff --name-status -z` workloads in `bench_git_query_ops` show parse is single-digit microseconds next
  to multi-millisecond subprocess cost.
- `sase ace` cold open is ~19% slower under Rust on the synthetic Pilot harness. The harness mocks
  `find_all_changespecs`, so the Rust scan/parse hot paths are not exercised; what remains is AceApp / Pilot constructor
  cost plus per-call PyO3 dispatch overhead at small inputs. Treat it as a known small-input dispatch tax, not a
  routed-op regression.
- `sase run` startup is dispatch-neutral at the cold-import scope: the cost users pay before the dispatcher can call any
  LLM is dominated by Python interpreter startup + sase package import.

### Performance regression floor

`tests/perf/baselines/phase7_regression_floor.json` pins absolute Rust ceilings for the anchors that matter
(`golden_myproj` and `synthetic_200_specs` for `parse_project_bytes`, `parse_only` for `parse_query`,
`synthetic_6p_200pp` for `scan_agent_artifacts`, `golden_myproj_pure` for `apply_status_update`, the
`synthetic_1000_specs` persistent query-corpus product route, and the synthetic 5k notification-store snapshot/mutation
routes). The relative `must_beat_python` check is disabled for anchors whose Python halves were deleted in Phase 8D —
only the absolute Rust ceiling stays in force. `parse_query.parse_only.direct` and the persistent query-corpus product
route keep `must_beat_python: true` because both comparable rows are still produced by the current harnesses. The CI
`phase7-perf-floor` GitHub Actions job runs the checker (`tests/perf/phase7_check_regression.py`) on every PR and
uploads `rust_backend_phase7_floor_check.json` as the build artifact.

`sdd/plans/202605/perf_artifacts/agent_launch_phase1_baseline.json` pins the launch migration baseline. The
`launch-perf-floor` GitHub Actions job runs `just launch-perf-check` on every PR and uploads
`agent_launch_regression_check.json` so a fan-out latency regression has a comparable report.

### Triage support note

When investigating a Rust-extension issue:

- **Confirm the extension is loaded.** `sase core health` (or `sase core health -j` for scripts) prints the
  `sase_core_rs` module path / version and the result of cheap parser, launch, and bead binding probes. Exit code 0
  means the extension loaded and worked; non-zero means the wheel is missing, stale, or misbuilt.
- **Recognise a wheel-load failure.** A missing or stale extension surfaces as `ImportError` / `AttributeError` from a
  shipped operation, or as `sase core health` exit code 1 with `error_kind` / `error` fields naming the underlying
  import error. The publish-workflow `install-smoke` runs `sase core health` on every release and dumps `pip list` plus
  `sase_core_rs.__file__` / `__version__` on failure.
- **There is no env-var escape hatch.** If `sase_core_rs` is broken, the user-facing fix is reinstalling sase or pinning
  to a known-good `sase-core-rs` version, not setting an env var. See the [Rollback](#rollback) section below.

## Verifying The Backend

A handful of commands cover "is my install healthy?" end-to-end:

```bash
sase core health             # Rust health: status + module path + version + platform
sase core health -j          # same, JSON for scripting

just check                   # full lint + type + test pass
just rust-check              # cargo fmt --check + clippy + cargo test (requires sibling ../sase-core checkout)
just bead-perf-smoke         # tiny Rust-backed bead shell/facade/work-plan benchmark
just launch-perf-check       # launch fan-out regression floor against the Phase 1 baseline
just phase7-perf-check       # Phase 7 regression-floor check against the recorded Rust ceilings
```

CI runs the full test suite under CPython 3.12 / 3.13 / 3.14 (`.github/workflows/ci.yml`). The dedicated `bead-backend`
job checks the sibling Rust core (`just rust-check`), focused Python bead tests, cross-repo bead facade parity tests,
and `just bead-perf-smoke`. The publish workflow's `install-smoke` job installs the built `sase` wheel into a fresh venv
and runs `sase core health`; on failure it dumps `pip list`, Python/platform info, and `sase_core_rs.__file__` /
`__version__` so missing-wheel or ABI-mismatch failures are diagnosable from the build log without a manual repro.

## Golden Contract

After Phase 8 the Python halves of the ported operations are gone, so the compatibility seam is the _golden corpus_
rather than a live Python/Rust dual-run comparison. The corpus pins the Rust extension's expected output byte-for-byte
across parser, query, agent scan, status, and Git query helpers:

| Surface                      | Tests                                                                                                                       |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| ChangeSpec parser            | `tests/test_core_golden.py`, `tests/test_core_wire.py`, `tests/test_core_facade/test_parser.py`                             |
| Query parse / canonical form | `tests/test_core_query_golden_*` (errors / eval / tokens / wire), `tests/test_core_facade/test_query.py`                    |
| Agent artifact scan          | `tests/test_core_agent_scan.py` + `tests/agent_scan_golden/` fixture builder                                                |
| Notification store           | `tests/test_core_notification_store.py`, `tests/test_core_facade/test_notification_store.py`                                |
| Status helpers + planner     | `tests/test_core_facade/test_status.py`, `tests/test_core_status_lines.py`, `tests/test_core_status_wire.py`                |
| Git query parsers            | `tests/test_core_git_query.py`                                                                                              |
| Agent launch                 | `tests/test_core_agent_launch_wire.py`, `tests/test_agent_launch_executor.py`, `tests/perf/test_agent_launch_regression.py` |
| Beads                        | `tests/test_bead/`, `tests/test_core_facade/test_bead_*.py`, `../sase-core/crates/sase_core/tests/bead_*`                   |
| Strict-loader contract       | `tests/test_core_rust.py`, `tests/test_core_health.py`                                                                      |

The `tests/core_golden/` corpus (`myproj.gp`, `myproj-archive.gp`) plus the `inline_snapshot` JSON expectations in
`test_core_golden.py` are the cross-language reference: any change to the Rust output that breaks a snapshot must be
matched by an equivalent change in the corresponding `sase-core` Rust parity test (`../sase-core/.../tests/`) before
either side ships.

## Rollback

After Phase 8 the rollback model is **wheel/package fix, not env-var workaround**. There is no `SASE_CORE_BACKEND`
escape hatch, no Python implementation to fall back to for ported operations, and no per-user mitigation that bypasses
Rust.

- A Rust-side regression is fixed and re-released as a `sase-core-rs` patch version that `sase` depends on. The pinned
  range is updated in `pyproject.toml` and a `sase` patch release pulls the corrected wheel.
- For a regression that drifted before Phase 8 closed, the only safe path is to revert the Phase 8 PR(s) that removed
  the Python halves, ship a patch release that restores the Python implementations, then redo verification before
  re-attempting the deletion.

If a user reports a `sase core health` failure post-release, the support workflow is:

1. Verify the installed `sase-core-rs` version (`pip show sase-core-rs` or the JSON output of `sase core health -j`).
2. Reinstall: `pip install --force-reinstall sase` (or `uv tool install --force sase`) to repull the wheel.
3. If the wheel itself is broken on the user's platform, pin to the previous `sase-core-rs` version and file a bug in
   `../sase-core` with the `sase core health -j` output, the platform tag, and the failing binding.

The Phase 6/7 release-cycle artefacts (`SASE_CORE_BACKEND=python` escape hatch, dual-run JSONL, `parity-gate` job) are
deleted; do not reach for them when triaging post-Phase-8 issues.

## Migration History

The migration ran across nine phases. Phases 0–7 added the Rust backend behind a default-Python escape hatch and the
parity gate; Phase 8 deleted the dispatcher, the dual-run plumbing, and the Python halves of every ported operation that
did not need them as host logic. The full per-phase narrative lives in `research/202604/rust_backend_migration.md` and
`sdd/epics/202604/rust_backend_phase{0..8}*.md`. The handoffs that record each subphase's changes are alongside their
plan files (`sdd/epics/202604/rust_backend_phase8_phase8{a..g}_handoff.md`).
