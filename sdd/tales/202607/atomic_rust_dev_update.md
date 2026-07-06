---
create_time: 2026-07-06 00:04:06
status: wip
prompt: sdd/prompts/202607/atomic_rust_dev_update.md
---
# Plan: Make the dev-update Rust reconcile atomic and self-healing

## Incident summary (what happened)

On 2026-07-05 at ~23:07, the user triggered an update of `sase` + `sase-core-rs` from the "Updates" tab of the SASE
Admin Center (both installed as editable dev checkouts). Immediately afterward, **every** `sase` invocation crashed at
startup with:

```
ModuleNotFoundError: No module named 'sase_core_rs.sase_core_rs'
...
ImportError: sase_core_rs is not importable in this environment but is a hard runtime
dependency of sase; reinstall with `just install` (or `just rust-install` ...)
```

The uv-tool venv's `sase_core_rs/` package directory still contained `__init__.py` (`from .sase_core_rs import *`) but
the compiled `sase_core_rs.abi3.so` was gone. The user had to manually `uv tool uninstall` + reinstall the published
PyPI version to recover.

## Root cause

The editable dev-update flow (`sase.dev_update`) runs, per actionable checkout: fetch → ff-only merge → reconcile steps.
When the core checkout changed, the reconcile steps are:

1. `uv tool install` (full `--with` set) — recreates the tool venv; this installs a **working** `sase-core-rs` wheel
   from PyPI as a dependency of `sase`.
2. `just rust-install-uv-tool` → `just rust-install <tool-venv>`, whose recipe is: validate version → ensure maturin →
   **`tools/purge_sase_core_rs_extensions`** (deletes every `sase_core_rs*.{so,pyd,dll,dylib}` from the venv) →
   `maturin develop --release`.

The recipe is **destroy-then-rebuild**: the moment the purge runs, the environment is broken until `maturin develop`
completes (a cold `--release` build: dependency downloads + full compile). Any failure or kill in that window strands
the venv with `__init__.py` but no native extension — which is exactly what happened.

Forensics from the incident machine:

- Both dev checkouts fast-forwarded at 23:07:31–32 (git reflogs), so the merge phase succeeded.
- `tools/validate_sase_core_rs_version` passes for that state, so the flow reached the purge.
- `~/.cargo/registry` did not exist afterward and no `target/` dir existed in the sase-core checkout — cargo never got
  as far as fetching dependencies, i.e. `maturin develop` died at the very start of the step.
- Not a compile error: the same `maturin develop --release` at the same sase-core commit (0f283f0) builds cleanly in
  ~43s.
- Not the `DEV_UPDATE_COMMAND_TIMEOUT_SECONDS = 300` cap: the TUI path runs reconcile commands through
  `TaskReporter.run` → `stream_subprocess` with `timeout=None`.
- Most consistent surviving explanation: the step's process group was SIGTERM/SIGKILLed via `stream_subprocess`'s
  `cancel_event` (task cancel, TUI quit, or the post-update restart-that-stops-background-tasks path) or a transient
  cargo/network failure on the fully cold cargo cache. The exact trigger is unrecoverable because **nothing about the
  run was persisted** — the tracked-task log lives only in the TUI session that restarted/exited.

Compounding defects:

- The broken state is _worse than not running step 2 at all_: step 1 had just installed a working PyPI wheel that the
  purge then deleted.
- A broken `sase_core_rs` makes `sase` itself unlaunchable (hard dependency checked at startup), so the product cannot
  self-diagnose or self-repair.
- The `require_rust_extension` error message recommends `just install` / `just rust-install`, which repair a _project_
  venv — the wrong remediation when the broken environment is the uv-tool venv.

## Goals

1. A failed or interrupted Rust rebuild must never leave a venv without a loadable `sase_core_rs` (crash-safe swap;
   preserve the previous extension until the new one exists).
2. Dev updates must verify the environment actually works after reconcile, and automatically fall back to the published
   wheel if it does not.
3. Dev-update runs must leave a persistent on-disk record so failures can be diagnosed post-mortem (this incident
   destroyed its own evidence).
4. When the startup guard does fire, its remediation advice must match the actual install context (uv-tool venv vs.
   project venv).

## Non-goals

- Pinning down the exact 23:07 kill/failure trigger (evidence gone; goal 3 fixes that for next time).
- Changing the managed (non-editable) `uv tool upgrade` path — it swaps wheels atomically via uv and was not at fault.
- Rust-side (`sase-core`) changes: this is host install/build tooling, which belongs in this repo per the core-boundary
  rule.

## Design

### 1. Crash-safe `just rust-install` (build first, purge stale artifacts last)

Reorder the recipe so nothing is deleted before a replacement exists:

- Drop the pre-build purge. Run `maturin develop --release` directly; it overwrites the current `sase_core_rs.abi3.so`
  in place only during its brief install phase (file copy), shrinking the vulnerable window from minutes of compile time
  to milliseconds.
- Preserve the purge's original purpose (stale differently-tagged artifacts, e.g. `sase_core_rs.cpython-312-darwin.so`,
  shadowing fresh abi3 builds — see commit 6134949df) by purging **after** a successful build, excluding the artifact(s)
  the build just installed. Concretely, extend `tools/purge_sase_core_rs_extensions` with a freshness cutoff (e.g.
  `--exclude-newer-than <marker-file>`): the recipe touches a marker file before invoking maturin, then after success
  deletes only matching artifacts older than the marker.
- All `rust-install` call sites (project venv install paths and `rust-install-uv-tool`) get this for free since they
  share the recipe.

Failure matrix after the change: build fails or is killed → venv keeps the previous working extension; kill during
maturin's install copy → tiny window, and step 2 below still repairs it.

### 2. Post-reconcile health check + automatic fallback to the published wheel

Append a final verification step to the dev-update reconcile plan whenever the core package was part of the update (in
`sase.dev_update.plan._reconcile_steps` / executed by `sase.dev_update.execute`):

- Health check: `<tool-venv>/bin/python -c "import sase_core_rs"`.
- On failure, repair instead of merely reporting: reinstall the published wheel that satisfies the host checkout's
  `sase-core-rs` constraint (from the host `pyproject.toml`) into the tool venv via
  `uv pip install --python <tool-venv-python> --force-reinstall 'sase-core-rs<spec>'`, then re-run the health check.
- Surface the outcome distinctly in the task result: "dev Rust build failed; environment restored to published
  sase-core-rs X.Y.Z" (failure toast, but the user still has a working `sase`).

This protects against _every_ failure mode of step 1 (including SIGKILL mid-copy) and reuses the same step machinery, so
the CLI `sase update` path and the TUI path both benefit. The mode-switch flow can adopt the same helper as a follow-up.

### 3. Persist dev-update execution records

`execute_dev_update` already accumulates every executed command (argv, cwd, exit code, stdout/stderr) in
`DevUpdateResult.commands` — it is simply never written anywhere. Add a small appender that writes one JSONL record per
run (timestamp, plan summary, per-command results truncated to sane tails, final outcome) to
`~/.sase/logs/dev_update.jsonl`, called from both call sites (TUI tracked task completion and the `sase update`
handler). This record must be written even when the run fails or the TUI restarts immediately afterward.

### 4. Don't let the post-update restart kill an in-flight reconcile

`_restart_after_update` restarts ACE and explicitly stops running background tasks. If any update/dev-update tracked
task is still running (e.g. a second update task), defer the restart until it completes rather than killing it
mid-reconcile. With workstream 1 in place a kill is no longer destructive, but deliberately SIGKILLing a
package-management step remains a footgun.

### 5. Context-aware remediation in `require_rust_extension`

In `src/sase/core/rust.py`, detect whether the running interpreter lives in the uv-tool venv (e.g. `sys.prefix` under
`$(uv tool dir)/sase`) and tailor the ImportError message:

- uv-tool context: recommend `uv pip install --python "<tool-venv>/bin/python" --force-reinstall sase-core-rs` (fast,
  keeps receipt) and `uv tool install --force sase` as the big hammer.
- project venv context: keep the existing `just install` / `just rust-install` guidance.

## Files expected to change

- `justfile` — `rust-install` recipe reorder (marker file, post-build stale purge).
- `tools/purge_sase_core_rs_extensions` — freshness-cutoff option; keep default behavior for any other callers.
- `src/sase/dev_update/plan.py`, `src/sase/dev_update/models.py`, `src/sase/dev_update/execute.py` — health-check/repair
  step kind, execution, and result plumbing; JSONL run-record writer (new small module, e.g.
  `src/sase/dev_update/journal.py`).
- `src/sase/ace/tui/modals/plugins_browser_sase_update.py` — journal hookup; restart deferral.
- `src/sase/main/update_handler.py` — journal hookup for the CLI path.
- `src/sase/core/rust.py` — context-aware error message.
- Tests: `tests/test_rust_install_cleanup.py` (purge cutoff), dev_update plan/execute tests (step ordering: health check
  last; repair-on-failure; journal record shape), rust.py message tests.

## Testing & verification

- Unit tests as listed above (the purge tool and dev_update modules are pure/injectable).
- Manual end-to-end: in a scratch uv-tool-style venv, simulate the incident — kill `just rust-install`
  mid-`maturin develop` — and verify `import sase_core_rs` still works afterward; then verify the dev-update
  health-check step repairs a deliberately broken venv (deleted `.so`).
- `just check` for the repo gates.

## Risks / notes

- `maturin develop` (not wheel install) is retained deliberately: it writes the editable `direct_url.json` metadata that
  the runtime inventory uses to classify `sase-core-rs` as an editable install — switching to a plain wheel install
  would silently drop the core checkout from future dev-update planning.
- The freshness-cutoff purge must handle both artifact layouts the original fix covered (inside `sase_core_rs/` package
  dir and flat in site-packages).
- The auto-repair step needs the network; when offline it should report the broken state clearly and leave the (already
  persisted) journal for diagnosis.
