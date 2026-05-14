# Factoring Built-In Chops into a Rust `sase-chops` Repo

Date: 2026-05-14

## Executive Summary

Factoring important built-in chops into a dedicated `sase-chops` repo is worth doing, but the best implementation is
not a big-bang rewrite of every current Python chop script.

The best shape is:

1. Create a Rust workspace in a new `sase-chops` repo.
2. Ship Rust executable chops as a Python-installable binary wheel, so normal `pip install sase` / `uv tool install
   sase` users do not need a Rust toolchain.
3. Keep the current external script protocol (`sase_chop_<name> --context <context.json>`) as the compatibility
   boundary.
4. Put shared domain logic in `sase_core`, not in `sase-chops`, and have `sase-chops` depend on the pure Rust
   `sase_core` crate.
5. Port self-contained filesystem/state chops first (`wait_checks`, then digest/cleanup/state transforms), and defer
   hook/mentor/workflow launcher chops until their Python-owned execution dependencies are split into Rust planners and
   Python executors.

The core reason: axe already runs script chops out-of-process, streams their stdout/stderr into per-chop run history,
dedupes live runs, applies timeouts, and discovers `sase_chop_<name>` executables on `PATH`. Replacing Python
entry-point scripts with real Rust binaries fits this architecture directly and avoids Python interpreter startup on
high-frequency scheduled work.

## Current Local Architecture

### Built-in chops and their schedules

Current built-in script chops are registered as Python console scripts in `pyproject.toml`, grouped under five
lumberjacks in `src/sase/default_config.yml`. Frequency and timeout matter for the Rust port because they set the
ceiling on per-invocation overhead a rewrite can save.

| Lumberjack | Interval | Chop timeout | Chops |
|---|---|---|---|
| `hooks` | 5s | 90s | `hook_checks`, `mentor_checks`, `workflow_checks`, `pending_checks_poll`, `comment_zombie_checks`, `suffix_transforms`, `orphan_cleanup` |
| `waits` | 2s | (default) | `wait_checks` |
| `checks` | 300s | (default) | `cl_submitted_checks`, `stale_running_cleanup` |
| `comments` | 60s | (default) | `comment_checks` |
| `housekeeping` | 3600s | (default) | `error_digest` |

`pushgateway_cleanup` is registered as an entry point but is not in any default lumberjack — it is invoked manually or
by user-extended config. The `waits/2s` and `hooks/5s` cadences are where Rust startup savings compound: a 2s interval
means ~43,200 invocations/day per active sase user.

Current built-in script chops are registered as Python console scripts in `pyproject.toml`:

- `sase_chop_hook_checks`
- `sase_chop_mentor_checks`
- `sase_chop_workflow_checks`
- `sase_chop_pending_checks_poll`
- `sase_chop_comment_zombie_checks`
- `sase_chop_suffix_transforms`
- `sase_chop_orphan_cleanup`
- `sase_chop_stale_running_cleanup`
- `sase_chop_pushgateway_cleanup`
- `sase_chop_wait_checks`
- `sase_chop_cl_submitted_checks`
- `sase_chop_comment_checks`
- `sase_chop_error_digest`

The scheduler-side contract is already good for a language boundary:

- `src/sase/axe/chop_script_runner.py` discovers external scripts by configured exact-name paths, then by
  `sase_chop_<name>` beside the active Python interpreter, then by `PATH`.
- Script chops are invoked as `<script> --context <context.json>`.
- `src/sase/axe/chop_runner.py` owns live-run dedupe, per-run metadata, stdout/stderr streaming, timeout handling,
  missing-script records, and scheduled/manual/oneshot provenance.
- `src/sase/axe/lumberjack.py` writes the per-tick context and serialized ChangeSpec files, then runs eligible script
  chops concurrently while launching configured agent chops sequentially.

That means a Rust chop binary can be swapped in without changing the AXE TUI or run-history model, provided it preserves
the CLI and output contract.

### Subprocess contract a Rust chop must honor

The existing Python scripts inherit several non-obvious behaviors from the runner. A Rust port that ignores any of
these will silently misbehave under AXE.

- **CLI shape**: `<script> --context <path>`. Exactly one positional/flag pair. No subcommands. `--help` and
  `--version` should also work for parity with `sase axe lumberjack list`.
- **Context format**: JSON file matching `ChopScriptContext` (see `src/sase/axe/chop_script_context.py`). Fields:
  `max_hook_runners`, `max_agent_runners`, `zombie_timeout_seconds`, `query`, `lumberjack_name`, `state_dir`,
  `all_changespecs_file`, `filtered_changespecs_file`, `verbose_lumberjack_diagnostics`. The Rust port must tolerate
  unknown extra fields (forward compatibility) and must reject older clients that omit required fields with a clear
  error rather than panicking.
- **ChangeSpec input**: read via the `all_changespecs_file` / `filtered_changespecs_file` paths, not via stdin.
  Schemas match the dataclasses in `src/sase/ace/changespec.py`. This is the largest serialization surface area and
  should be modeled in `sase_core` first so both Python and Rust share types.
- **Environment variables injected by the runner** (`src/sase/axe/chop_agents.py`):
  `SASE_CHOP_LUMBERJACK`, `SASE_CHOP_NAME`, `SASE_CHOP_RUN_ID`, `SASE_CHOP_PROMPT_HASH`. Rust binaries should read but
  must not require these — they are diagnostic-only and absent in oneshot/manual modes.
- **Stdout/stderr merging and live streaming**: `stream_chop_script` merges stderr into stdout with
  `bufsize=0` and a per-65 KiB pump thread. A Rust binary that buffers a full BufWriter for the whole run will not
  appear in the AXE live-output panel until exit. Rust ports should set stdout to line buffered (`LineWriter`) and
  call `flush()` after each summary line.
- **Process group / timeout-kill behavior**: subprocesses are launched with `start_new_session=True` and SIGKILL'd via
  `killpg` on timeout. A Rust chop that spawns long-lived background grandchildren (e.g. via `Command::spawn`) must
  not detach from the process group — otherwise the grandchild keeps the stdout pipe open and the parent pump thread
  stalls past timeout (see the explicit `pump_thread.join(timeout=5)` workaround in `chop_script_runner.py`).
- **Atomic file mutation**: the Python helper `_atomic_json_write` uses `tempfile.mkstemp` + `os.replace` in the same
  directory. Rust ports that write `ready.json`, digest markers, etc. should use `tempfile::NamedTempFile::persist`
  in the same directory to match crash-safety semantics.
- **Exit codes**: today the runner records the raw `returncode`; on timeout it is `None`. Standardizing to
  `0` (ok), `1` (operational failure), `2` (bad input/schema) keeps run history readable and avoids ambiguous
  `None` outcomes for in-binary failures.

The current scripts are not all equivalent candidates:

| Chop group | Current shape | Rust suitability |
|---|---|---|
| `wait_checks` | Standalone filesystem scan over `~/.sase/projects/.../artifacts/ace-run` and JSON markers. | Best first port. Self-contained, high-frequency (`waits` interval is 2s), no LLM/provider dependency. |
| `error_digest` | Reads axe errors, sends notification digest, writes last digest timestamp. | Good after notification/state helpers are Rust-owned. |
| `stale_running_cleanup`, `orphan_cleanup`, `pushgateway_cleanup` | Cleanup/state maintenance. | Good if workspace-claim/state mutation is exposed through `sase_core`. |
| `suffix_transforms`, `comment_zombie_checks` | ChangeSpec mutation logic. | Good medium-term candidates, but needs lock/parity tests because it mutates project files. |
| `cl_submitted_checks`, `comment_checks`, `pending_checks_poll` | Starts/polls background checks and external VCS/provider-sensitive operations. | Split into Rust scan/planner plus Python executor first. |
| `hook_checks`, `mentor_checks`, `workflow_checks` | Thin wrappers around `HookJobRunner`, which calls Python scheduler modules, launches hooks/agents/workflows, mutates ChangeSpecs, and uses provider/workspace machinery. | Do last. A direct rewrite risks duplicating too much SASE orchestration. |

## Repository Boundary

The existing SASE memory says shared backend/domain behavior belongs in sibling `../sase-core/crates/sase_core`, with
Python/TUI code calling through bindings or thin adapters. `sase-chops` should respect that boundary:

- `sase_core`: shared domain logic, wire types, parsers, filesystem scanners, notification store, status transforms,
  workspace-claim planners.
- `sase-chops`: operational binaries that read chop context, call `sase_core`, print concise operational summaries, and
  exit with meaningful codes.
- `sase`: scheduler, TUI, configuration, run history, Python provider integrations, fallback wrappers during migration.

Do not make `sase-chops` a second domain-core repository. That would create drift with the already-shipped Rust core.

## Packaging Decision

Best packaging for end users: publish a Python wheel distribution, likely named `sase-chops-rs` or `sase-chops`, that
contains Rust binaries named exactly like the current entry points: `sase_chop_wait_checks`,
`sase_chop_error_digest`, etc.

This fits the current discovery logic because `discover_chop_script()` already looks in the virtualenv bin directory
and then on `PATH` for `sase_chop_<name>`.

Recommended package layout:

```text
sase-chops/
  Cargo.toml
  crates/
    sase_chops_core/
      src/context.rs
      src/output.rs
      src/wait_checks.rs
      src/error_digest.rs
      src/...
    sase_chops_cli/
      src/main.rs
      src/bin/sase_chop_wait_checks.rs
      src/bin/sase_chop_error_digest.rs
      src/bin/sase_chop_stale_running_cleanup.rs
      ...
    sase_chops_py/
      pyproject.toml
      Cargo.toml
```

Two viable binary strategies:

1. **Preferred for compatibility:** multiple `src/bin/sase_chop_<name>.rs` binaries, each a tiny wrapper around
   `sase_chops_core::run("<name>", args)`.
2. **Acceptable later:** one `sase-chops run <name> --context ...` binary plus generated compatibility wrappers. This
   reduces duplicated binary bodies but adds one more packaging step.

For the first release, multiple binaries are simpler and match Cargo's native model. The Cargo Book documents that a
package can have multiple binary targets and that binaries can use the package library API.

Use `maturin`'s `bin` binding mode to put Rust binaries into the Python wheel. Maturin documents that `bin` bindings
install Rust binaries as scripts on the user's `PATH`. Avoid mixing PyO3 library bindings into the same wheel unless
there is a strong reason; maturin's docs call out that shipping both a binary and library can double wheel size.

For developers, `cargo install --path crates/sase_chops_cli --bins` can be supported as a secondary path. It should not
be the primary install story because normal SASE users should not need Rust.

### Cross-platform packaging

The published wheels should target the same matrix `sase-core/.github/workflows/release.yml` already covers: Linux
x86_64 + aarch64 (manylinux2014), macOS universal2, Windows x64. Since `bin`-binding wheels are
platform-specific but Python-version-independent (they ship native binaries, not extension modules), the matrix is
smaller than for PyO3 wheels — a single wheel per platform/arch.

Two cross-platform discovery gaps need fixing in `discover_chop_script` before Windows works:

- The direct `bin_dir / prefixed` check does not append `.exe` on Windows. `shutil.which` does, so the PATH fallback
  works, but the venv-bin fast path will miss Rust binaries. Fix this in the discovery helper rather than the chop
  package.
- File-mode executability checks (`os.access(..., os.X_OK)`) are unreliable on Windows. Either use
  `pathlib.Path.suffix == ".exe"` or rely entirely on `shutil.which` on Windows.

These changes are pre-requisites in the `sase` repo, not the new `sase-chops` repo.

### Co-installation shadowing risk

During migration, both `sase` (with Python entry points) and `sase-chops` (with Rust binaries) will install
`sase_chop_<name>` executables into the same venv `bin/`. With pip, the last-installed wheel wins — install order
silently determines which language runs each chop.

Three mitigations, in order of preference:

1. As soon as a chop is migrated, drop the matching Python entry point from `pyproject.toml` and replace
   `src/sase/scripts/sase_chop_<name>.py` with a thin `_legacy` module behind a config-gated wrapper. Eliminates the
   ambiguity per chop.
2. Until step 1 lands, name unmigrated Python entry points unchanged but route migrated ones through a configured
   `chop_script_dirs` directory that is checked first in `discover_chop_script`. This lets the venv `bin/` keep both
   without conflict.
3. Add a startup self-check (`sase axe lumberjack doctor`) that resolves each chop name and reports the resolved path
   and language, so users can see what is running.

## Versioning and Protocol

Add an explicit protocol version before routing any built-in chop to Rust:

- `ChopScriptContext.schema_version`: start at `1`.
- `sase-chops --version`: include package version and supported protocol range.
- SASE dependency pin: `sase-chops-rs>=0.1,<0.2`.
- Rust chop startup should fail fast with a compact message when the context schema is newer than it supports.

The context should remain file-oriented. Passing paths to `all_changespecs.json` and `filtered_changespecs.json` avoids
large argv/env payloads and keeps the subprocess contract language-neutral.

## Migration Plan

### Phase 0: Measure and Freeze Contracts

- Capture per-chop runtime, startup, output, and mutation behavior for current Python scripts.
- Add fixtures for `context.json`, `all_changespecs.json`, `filtered_changespecs.json`, axe state, and representative
  `~/.sase/projects` artifact trees.
- Define the output contract: every no-op emits a bounded one-line summary; action paths include counts and target IDs.
- Add a feature flag or config switch for built-in Rust routing, with Python scripts retained as oracle initially.

### Phase 1: New Repo and Packaging Skeleton

- Create `sase-chops` Rust workspace.
- Depend on `sase_core` by git/path initially; publish once the API stabilizes.
- Add CI: `cargo fmt`, `cargo clippy --workspace --all-targets -- -D warnings`, `cargo test --workspace`.
- Add release workflow mirroring `sase-core`: Linux x86_64/aarch64, macOS universal2, Windows x64, sdist fallback.
- Build a binary wheel and smoke-test that `sase_chop_wait_checks --help` works from a fresh venv.

### Phase 2: Port `wait_checks`

Port `wait_checks` first because it is high-frequency and self-contained. It currently:

- scans project artifact directories;
- reads `agent_meta.json`, `done.json`, and `waiting.json`;
- resolves named and workflow dependencies;
- writes `ready.json`;
- emits a compact count summary.

Implementation notes:

- Reuse or extend the existing Rust agent artifact scan/index machinery in `sase_core`.
- Use atomic write for `ready.json`.
- Preserve the exact success rule: only the newest matching named agent, or newest successful workflow root plus
  successful children, resolves `%wait`.
- Add Python/Rust parity fixtures for missing projects, invalid waiting markers, failed dependencies, live/no-done
  dependencies, older successful runs shadowed by newer failures, and workflow-child failures.

Routing gate:

- Rust output matches expected summaries.
- File mutations match Python on fixtures.
- Scheduled AXE manual smoke shows run history and live output unchanged.
- Rust is measurably faster or at least eliminates Python startup on the no-op path.

### Phase 3: Port Digest and Cleanup Chops

Good next ports:

- `error_digest`, after axe error-state and notification append/read helpers are available through `sase_core`.
- `stale_running_cleanup` and `orphan_cleanup`, after workspace-claim planning/mutation APIs are stable.
- `pushgateway_cleanup`, if it remains a simple isolated script.

These should keep the same subprocess shape and should not directly import or embed Python.

### Phase 4: Port Pure ChangeSpec State Transforms

Port `suffix_transforms` and `comment_zombie_checks` as Rust operations over `ChangeSpecWire` plus locked project-file
mutation helpers. These are good performance and correctness candidates, but they need stronger tests than `wait_checks`
because they mutate user-visible project files.

Required gates:

- byte-level project-file mutation parity or an intentional documented normalization;
- concurrent mutation tests;
- SASE TUI and `sase axe lumberjack run hooks` smoke tests.

### Phase 5: Split Launcher Chops into Planner/Executor

Do not directly rewrite `hook_checks`, `mentor_checks`, `workflow_checks`, `cl_submitted_checks`, `comment_checks`, or
`pending_checks_poll` as all-Rust executors at first.

Instead:

- Move pure scan/planning decisions to Rust.
- Keep provider invocation, agent launch, workspace-provider hooks, and external VCS command execution in Python until
  those host bridges are explicitly Rust-owned.
- Have Rust return planned actions; Python applies actions through existing, tested execution code.

This avoids duplicating the most failure-prone parts of SASE's orchestration stack.

## Design Details

### CLI

Use `clap` derive for predictable argument parsing:

```text
sase_chop_wait_checks --context <path>
sase_chop_error_digest --context <path>
sase-chops run wait_checks --context <path>   # optional aggregate command
sase-chops list
sase-chops doctor
```

The individual binaries should support at least:

- `--context <path>`
- `--json` for machine-readable summaries, if useful later
- `--version`

### Output

Keep stdout/stderr human-readable because the AXE tab displays per-chop output directly. A good no-op line looks like:

```text
wait_checks: projects=12 artifacts=181 waiting=0 ready_written=0 reason=no_waiting_markers
```

Use structured-ish key/value text, not JSON by default, because current AXE rendering is optimized for readable logs.

### Error Handling

Use typed Rust errors internally, but exit codes should remain simple:

- `0`: completed successfully, including no-op.
- `1`: operational failure.
- `2`: bad CLI/context/schema.

Any failure should print enough information for the AXE run-history panel to diagnose it without requiring a separate
traceback file.

### Testing

Each port should have three layers:

- Rust unit tests around pure decision logic.
- Fixture parity tests comparing old Python script behavior with Rust output/mutations.
- SASE integration tests proving scheduler discovery, timeout, run-history status, and TUI/manual run behavior still
  work.

For migrated chops, keep Python scripts as fallback/oracle until routed Rust behavior clears the parity and timing
gates on live-ish fixture trees.

### Logging and telemetry

Current Python chops use the standard `logging` module with output going through stdout/stderr (and from there to the
AXE per-run log file). The Rust ports should:

- Use `tracing` with a `tracing-subscriber` `fmt` layer writing to stdout, configured for compact human-readable
  output (no ANSI by default, since AXE may render the log directly).
- Honor `RUST_LOG` and `SASE_CHOP_LOG` for level overrides.
- Avoid colored output unless `verbose_lumberjack_diagnostics` is set in the context.
- For chops that today push to Prometheus pushgateway (`pushgateway_cleanup` and any Prom-emitting code in
  `error_digest`), reuse `sase_core` Prometheus helpers rather than pulling in the `prometheus` crate at the chop
  layer. Keep the binary thin.

## Performance Estimate

Order-of-magnitude numbers, useful for sizing the win before committing:

- CPython 3.12 cold start with `import sase.scripts`: ~150–250 ms on a typical dev laptop, dominated by import-time
  side effects (the `sase` package pulls in textual, dataclasses, configuration, etc.).
- Equivalent Rust binary cold start: ~3–10 ms.
- `wait_checks` runs every 2s and is currently a near no-op when no `waiting.json` markers exist; the entire wall-clock
  cost today is roughly Python startup. A Rust port reclaims ~150 ms per invocation, ~64 minutes/day of CPU, while
  also reducing tail latency that delays scheduled hooks.
- `hooks` lumberjack runs 7 chops every 5s. Even if individual chops do real work, replacing 7×150 ms of startup with
  7×5 ms saves ~1 second/cycle and makes the 90s chop-timeout budget go further.

These numbers should be measured on real fixtures during Phase 0, not assumed. The point is that the savings come
from invocation count and startup, not from algorithmic speedups in the chops themselves.

## Alternatives Considered

### A. Keep chops as Python entry points, move logic to a `pyo3`-imported Rust crate

Each Python `sase_chop_<name>.py` would `import sase_core_rs` and call into Rust for the heavy work. No new repo.

Rejected because (a) it does not eliminate Python interpreter startup, which is the main per-invocation cost on
high-frequency lumberjacks; (b) it forces `sase_core_rs` to grow PyO3 surface area for every chop's full data flow,
which contradicts the existing memory rule that backend logic should stay pure Rust where possible; (c) it does not
test the standalone-Rust-binary execution path that future non-Python frontends (mobile, web, daemon) will eventually
need anyway.

### B. Add a `sase_chops` crate inside the existing `sase-core` workspace

Same code, same release. No new repo to maintain.

This is the legitimate competing option. Pros: single CI, single release, immediate access to `sase_core`
internals during prototyping, no cross-repo coordination tax. Cons: forces every chop change through the
`sase-core` semver/release cadence (slow); blurs the `sase-core = pure domain library` boundary; couples chop tests
to the core repo's manylinux/macOS matrix even though chops have different distribution requirements.

Recommendation: prototype as a crate in `sase-core` for Phase 0/1, then split into a separate repo only once the
binary distribution and CI story is proven. This avoids speculative repo overhead without locking the project in.

### C. Distribute via `cargo-dist`/standalone binary releases instead of a Python wheel

`cargo-dist` produces signed GitHub Releases with prebuilt binaries and an installer script.

Useful as a *secondary* channel for users who want to install chops without sase, or for sase's own daemon to
self-update binaries. Not a replacement for the wheel: most sase users install via `pip`/`uv tool install sase`, and
asking them to run a separate installer breaks the one-command install story.

### D. Bundle Rust chops into the existing `sase` Python wheel

Use maturin to build the `sase` package itself as a mixed Rust/Python wheel.

Rejected because the `sase` package is currently pure Python and cross-platform; converting it to a binary wheel
would force the whole release matrix to grow (per-platform builds for code that does not need them) just to ship
a few chop binaries. Keep the binary distribution scoped to a small dedicated package.

## Open Questions

- Should `sase-chops` re-export a minimal Python API (e.g. `from sase_chops import wait_checks`) so internal Python
  callers can invoke chop logic without the subprocess hop? Probably yes for testing, but only after the binary
  surface stabilizes.
- How should the Python `sase` repo declare its dependency? A loose `sase-chops-rs>=0.1` lets users upgrade
  independently; a pinned dependency forces lockstep but simplifies support. Lean toward loose with a documented
  compatibility matrix.
- Should the binary wheel ship debug symbols stripped or split? `sase-core` currently ships stripped binaries; match
  that until a debugging case forces otherwise.
- What is the owner/maintainer model for the new repo? If it stays a one-maintainer side project, the polyrepo
  overhead is harder to justify (see Alternative B).

## Recommendation

Proceed with a dedicated `sase-chops` repo, but constrain it to operational Rust binaries over `sase_core` APIs. Do not
move generic parsing, status, notification, workspace, or agent-scan logic into `sase-chops`.

The first concrete milestone should be a Rust `sase_chop_wait_checks` binary distributed via a Python binary wheel and
routed by the existing `discover_chop_script()` mechanism. That gives the highest signal: it tests the packaging,
protocol, scheduler, output, and performance story on the least entangled high-frequency chop.

Only after that works should the project port more built-ins. The launcher-heavy chops need a planner/executor split,
not a direct all-Rust rewrite.

## Sources

Local code and docs:

- `pyproject.toml`: current Python console-script entry points for built-in chops.
- `src/sase/axe/chop_script_runner.py`: external script discovery and streaming subprocess runner.
- `src/sase/axe/chop_runner.py`: shared single-chop run service, dedupe, run history, agent/script dispatch.
- `src/sase/axe/lumberjack.py`: scheduled context writing, eligibility checks, concurrent script chop execution.
- `src/sase/axe/chop_script_context.py`: current JSON context and ChangeSpec serialization contract.
- `src/sase/default_config.yml`: built-in lumberjack/chop schedule.
- `src/sase/scripts/sase_chop_*.py`: current built-in Python chop implementations.
- `docs/axe.md` and `docs/configuration.md`: public axe/chop configuration and script contract.
- `sdd/research/202604/rust_backend_migration.md`: shipped Rust-core migration foundation and packaging precedent.
- `sdd/research/202604/rust_core_next_candidates.md`: prior warnings about FFI granularity and Python orchestration
  boundaries.
- `src/sase/axe/chop_agents.py`: `SASE_CHOP_*` env var names that the runner injects.
- `src/sase/default_config.yml` (axe section): canonical lumberjack/chop schedule and timeouts used in the table above.
- `../sase-core/Cargo.toml`, `../sase-core/.github/workflows/release.yml`, `../sase-core/crates/sase_core_py/src/lib.rs`:
  existing Rust workspace, wheel matrix, and pure-core/PyO3 split.

External docs:

- Maturin bindings: https://www.maturin.rs/bindings.html
- PyO3 building and distribution: https://pyo3.rs/main/building-and-distribution
- Cargo targets: https://doc.rust-lang.org/cargo/reference/cargo-targets.html
- `cargo install`: https://doc.rust-lang.org/cargo/commands/cargo-install.html
- Clap derive reference: https://docs.rs/clap/latest/clap/_derive/index.html
- `tracing-subscriber` fmt layer: https://docs.rs/tracing-subscriber/latest/tracing_subscriber/fmt/index.html
- `tempfile::NamedTempFile::persist`: https://docs.rs/tempfile/latest/tempfile/struct.NamedTempFile.html#method.persist
- `cargo-dist`: https://opensource.axo.dev/cargo-dist/
