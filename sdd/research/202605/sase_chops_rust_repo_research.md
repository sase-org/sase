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
- `../sase-core/Cargo.toml`, `../sase-core/.github/workflows/release.yml`, `../sase-core/crates/sase_core_py/src/lib.rs`:
  existing Rust workspace, wheel matrix, and pure-core/PyO3 split.

External docs:

- Maturin bindings: https://www.maturin.rs/bindings.html
- PyO3 building and distribution: https://pyo3.rs/main/building-and-distribution
- Cargo targets: https://doc.rust-lang.org/cargo/reference/cargo-targets.html
- `cargo install`: https://doc.rust-lang.org/cargo/commands/cargo-install.html
- Clap derive reference: https://docs.rs/clap/latest/clap/_derive/index.html
