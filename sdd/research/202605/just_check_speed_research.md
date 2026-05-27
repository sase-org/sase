# `just check` Speed Research

Date: 2026-05-27

## Question

How should SASE make `just check` much faster without losing the confidence agents rely on before handing work back?

## Executive Summary

The biggest win is not another `xdist` knob. The current test suite is accidentally reading the live
`~/.sase/projects` tree during launch-name validation, even though `tests/conftest.py` intends to redirect `~/.sase`
state to per-test temp directories. On this machine that live tree is about 1.0 GB and contains 13,509
`agent_meta.json` files. Launch-path tests repeatedly scan or stat that tree through the agent-name registry.

Measured impact:

- Normal `just test`: `10067 passed, 6 skipped` in 94.37s pytest time.
- `just test` with `HOME` pointed at an empty directory: same test count in 36.40s pytest time.
- One launch test dropped from a 2.41s call to a 0.26s call when the live home tree was removed from the path.

So the best first implementation is to fix SASE home path isolation for code that currently uses
`Path.home() / ".sase"`, starting with `src/sase/agent/names/_registry.py`. That should take the test stage from roughly
94s to roughly 36-38s. Since non-test `just check` stages cost about 17s serially, this should put full `just check`
near 50-60s without changing what it checks.

After that, parallelizing independent non-test stages should save another roughly 10s. Change-aware check selection can
make common agent turns much faster, but that is a semantic change and should be introduced alongside an explicit
`just check-full` CI target.

## Current `just check`

`Justfile` currently defines:

```just
check: _setup
    @tools/run_silent "fmt (python)"       just fmt-py-check
    @tools/run_silent "fmt (markdown)"     just fmt-md-check
    @tools/run_silent "lint (keep-sorted)" just lint-keep-sorted
    @tools/run_silent "lint (ruff)"        just _lint-ruff
    @tools/run_silent "lint (mypy)"        just _lint-mypy
    @tools/run_silent "lint (pyscripts)"   just _lint-pyscripts
    @tools/run_silent "lint (pyvision)"    just _lint-pyvision
    @tools/run_silent "SASE validation"     just validate
    @tools/run_silent "test"               just test
```

`tools/run_pytest fast` adds `-n <workers> --dist=loadfile -m "not slow"`. Because this command-line marker overrides
the `pyproject.toml` default `-m "not slow and not visual"`, the current `just test`/`just check` test stage includes
visual tests.

## Measurements

Environment:

- Python 3.14.3
- pytest 9.0.3
- pytest-xdist 3.8.0
- 64 CPU cores reported by `nproc`
- `tools/run_pytest` default worker count: `min(os.cpu_count(), 16)` = 16

Full baseline:

| Command | Result |
| --- | ---: |
| `hyperfine --runs 1 --show-output 'just check'` | 165.984s wall |
| `just test --durations=50` | 94.37s pytest time |
| `hyperfine --runs 1 'SASE_PYTEST_WORKERS=8 just test --durations=5'` | 112.641s wall |
| `hyperfine --runs 1 'just test --dist=worksteal --durations=5'` | 102.965s wall |
| `hyperfine --runs 1 'just test --dist=load --durations=5'` | 90.999s wall |
| `hyperfine --runs 1 '.venv/bin/python -m pytest --collect-only -q'` | 7.773s wall |

Non-test stage timings, each measured with one `hyperfine` run:

| Stage | Time |
| --- | ---: |
| `just fmt-py-check` | 0.201s |
| `just fmt-md-check` | 3.039s |
| `just lint-keep-sorted` | 0.020s |
| `just _lint-ruff` | 0.185s |
| `just _lint-mypy` | 0.535s |
| `just _lint-pyscripts` | 3.563s |
| `just _lint-pyvision` | 5.983s |
| `just validate` | 3.160s |

The summed non-test cost is about 16.7s when stages run serially.

Visual split:

| Command | Normal home | Empty `HOME` |
| --- | ---: | ---: |
| `just test -m "not slow and not visual" --durations=5` | 81.423s | 30.670s |
| `just test-visual --durations=5` | 33.314s | 31.781s |
| combined default `just test` | 94.37s pytest time | 36.40s pytest time |

The visual lane is not the main reason the suite is slow today. After fixing the home leak, skipping visual tests from
default `just check` would still save roughly 5-7s, but the path-isolation fix is much larger.

## Root Cause: Live `~/.sase` Scans During Tests

`tests/conftest.py` has an autouse fixture:

```python
redirect_sase_home(monkeypatch, tmp_path_factory.mktemp("sase_home"))
```

That helper patches `Path.expanduser` and `os.path.expanduser` for paths beginning with `~/.sase`. It does not patch
`Path.home()`, and it does not set the `HOME` environment variable. As a result, anything that builds a path through
`Path.home() / ".sase" / ...` skips the redirect entirely and points at the real home directory.

`src/sase/agent/names/_registry.py` uses `Path.home() / ".sase"` directly in several places:

- `_registry_path()`
- `_source_signature_paths()`
- `_collect_artifact_entries()`
- `_collect_dismissed_bundle_entries()`
- `_load_dismissed_suffixes()`

That bypasses the test redirect and points at the real home directory. On this machine:

```text
du -sh ~/.sase/projects
1011M  /home/bryan/.sase/projects

find ~/.sase/projects -path '*/artifacts/ace-run/*/agent_meta.json' -type f | wc -l
13509
```

`pyinstrument` on
`tests/test_cd_launch_from_cwd.py::test_launch_agent_from_cwd_alt_fanout_uses_named_child_prompts` showed the same
shape:

- 5.774s in `launch_agent_from_cwd`
- 4.175s under `validate_launch_name_requests`
- 4.174s under `is_name_reserved -> load_name_registry`
- 3.708s rebuilding the registry from live artifacts
- 1.985s collecting dismissed bundle entries
- 1.059s collecting artifact entries

With `HOME=/tmp/sase-check-home-empty`, the same single test changed from:

- normal: 12 tests in that file took 4.20s pytest time; the target test call was 2.41s
- empty home: the target test call was 0.26s and the whole single-test process was 3.073s wall

Important caveat: setting `HOME` for the entire `just check` command is not the implementation. It makes
`sase validate` fail `init --check` because the empty home is missing generated memory and skill files. The fix should
isolate the test/runtime path resolution, not run the whole check under a fake home.

### Scope of the Leak

The leak is not just one module. `Path.home()` is used in 77 places across `src/sase/` (most followed by
`/ ".sase" / ...`). Representative groupings:

- Agent-name registry: `agent/names/_registry.py` (and adjacent name modules).
- Project state: `agent/launch_cwd.py`, `agent/running.py`,
  `workspace_provider/store.py`, `workspace_provider/plugins/{bare_git_init,bare_git_ref,cd_workspace}.py`.
- History modules: `history/{file_references,prompt,hook,command,chat,chat_catalog}.py` — several of these capture
  `Path.home() / ".sase" / "<file>"` at **module import time** as module-level constants. That means even after the
  fix to use a helper, those constants must be evaluated lazily (function or cached property) or they will freeze the
  real home into the test process at import time and the redirect will not take effect.
- Memory + integrations: `memory/episodes/{collector,index}.py`, `memory/read_log.py`, `memory/proposals/paths.py`,
  `memory/cli_list.py`, `integrations/chat_install.py` (also has a module-level `_STATE_DIR`),
  `integrations/_mobile_*.py`.
- Scripts: `scripts/sase_chop_wait_checks.py`, `scripts/sase_migrate_statuses`.

The agent-name registry is the dominant test-time hot path today (confirmed by the `pyinstrument` profile and the
2.41s → 0.26s drop on the launch test). The rest still matters because future test additions exercising those code
paths would silently re-introduce the leak.

### Existing Partial Convention

`src/sase/integrations/_mobile_agent_paths.py:11` and `src/sase/integrations/_mobile_helper_common.py:121` already
define `sase_home()` helpers with the exact recommended shape:

```python
def sase_home() -> Path:
    return Path(os.environ.get("SASE_HOME") or Path.home() / ".sase")
```

`src/sase/ace/tui/repro/capture.py:365` and `src/sase/bead/workspace.py:226` also read `SASE_HOME`. So the pattern,
the env var name, and at least one in-repo helper already exist — the work is to consolidate them into a single
canonical helper and migrate the 70+ remaining callsites, not to invent a new convention.

Several tests already set `HOME` or `SASE_HOME` for isolation (e.g. `tests/test_mobile_helper_beads.py`,
`tests/workflows/test_commit_workflow.py:518`, `tests/test_cd_spawn_env.py:353`). The autouse fixture would simply
generalize that pattern.

## Recommended Implementation Sequence

### 1. Fix SASE Home Path Isolation

This is the highest-leverage first step. There are two complementary changes; do them together.

#### 1a. Conftest-level env override (small, immediate, broad)

In `tests/conftest.py`'s autouse `_isolate_sase_home` fixture, add:

```python
monkeypatch.setenv("HOME", str(fake_home))
monkeypatch.setenv("SASE_HOME", str(fake_home / ".sase"))
(fake_home / ".sase").mkdir(parents=True, exist_ok=True)
```

This single change makes every runtime call to `Path.home()` resolve inside the test temp directory because
`Path.home()` reads the `HOME` env var on POSIX. It also satisfies the four files that already honor `SASE_HOME`. The
existing `expanduser` monkey-patching can remain (defensive) or be removed once the env override is in place —
`os.path.expanduser` also follows `HOME`.

Caveats:

- Module-level captures (e.g. `_HISTORY_FILE = Path.home() / ".sase" / "..."`) are evaluated at first import, which
  often happens **before** the autouse fixture runs. For tests that import these modules later, the env override is
  sufficient; for modules imported during pytest collection (xdist worker boot), the captured constant freezes the
  real home. Step 1b handles that case.
- The existing fixture has a defensive `_home_env_overridden()` check that disables the `expanduser` redirect when a
  test changes `HOME`. With this change, the conftest itself sets `HOME`, so `initial_home_env` should be captured
  **before** the conftest setenv, otherwise the redirect will always be considered "overridden" and disable itself.
- A few tests intentionally set `HOME` to a literal value (e.g.
  `tests/workspace_provider/test_changespec_workflow_params.py:283` sets `HOME=/home/user`). Those keep working,
  because the per-test `monkeypatch.setenv` runs after the autouse fixture and wins.

#### 1b. Centralize `sase_home()` and migrate module-level constants

- Add a canonical helper at, e.g., `src/sase/paths.py` (or extend an existing paths module) that returns
  `Path(os.environ.get("SASE_HOME") or Path.home() / ".sase")`. Re-export from the existing integrations helpers so
  both implementations now delegate.
- Migrate the 70+ direct `Path.home() / ".sase" / ...` call sites in batches by area (registry → history → workspace
  providers → memory → scripts).
- Convert module-level constants in `history/{file_references,prompt,hook,command}.py` and
  `integrations/chat_install.py` from constants to small accessor functions (or `functools.cache`d functions) so the
  path is resolved per-call, not at import. This is the part that the conftest env override cannot fix on its own.
- Add a regression test that imports `sase.agent.names._registry`, asserts `_registry_path()` is under the test temp
  home, and fails loudly if the value escapes.

Expected result:

- `just test`: about 94s -> 36-38s (the registry hotspot alone is responsible for ~58s of suite time on this machine).
- `just check`: about 50-60s after adding the unchanged non-test stages.

This also fixes a correctness issue: tests that claim to avoid real SASE state are currently observing real state, and
that state is environment-dependent — CI runners and other developers have different `~/.sase/projects` contents, which
can mask or fabricate failures. Several intermittent CI symptoms historically attributable to "flaky tests" may share
this root cause; worth a sweep of the flake-tracking notes after the fix lands.

#### Risks and rollback

- A handful of tests may have been quietly depending on real-home state (e.g. expecting a real ChangeSpec to exist).
  The autouse env override would surface those as failures. Expect a small triage pass.
- The conftest env change is one line per env var; it is trivially revertable if a stubborn test breaks. The wider
  migration in 1b is incremental — landing it module-by-module keeps the blast radius small.

### 2. Parallelize Independent Non-Test Stages

The non-test stages are serial today and total about 16.7s. The longest stage is `pyvision` at about 6s. A small
`tools/check` Python orchestrator (or a parallel-aware bash dispatcher) could run independent checks concurrently
while preserving `tools/run_silent`-style failure output.

Safe parallel groups (all independent — none mutate the workspace, none depend on each other's output):

- Python formatting check, Ruff lint, mypy, pyscripts, pyvision.
- Markdown formatting check and keep-sorted lint.
- SASE validation. The `init --check` subcommand reads `~/.sase` and the repo, but does not write — safe to run in
  parallel with the linters.

If parallelism is set to the longest stage (~6s pyvision), the non-test wall time drops from ~16.7s to roughly 6-7s,
saving ~10s. On a 64-core machine the only resource pressure is the editable Python venv startup that each stage
pays; that is small.

#### Minimal `tools/run_silent_parallel` sketch

The simplest viable orchestrator is bash. Each stage logs to its own tempfile; failures dump in stable order; exit
code is the OR of all stages.

```bash
#!/usr/bin/env bash
# Usage: tools/run_silent_parallel <name1> <cmd1> -- <name2> <cmd2> -- ...
set -uo pipefail

# parse name/cmd pairs separated by '--' into arrays; launch each in background
# capturing stdout+stderr per stage; wait; print pass/fail; dump failed outputs
# in input order; exit nonzero if any failed.
```

A Python version reusing `tools/run_silent` semantics is straightforward too (`concurrent.futures.ThreadPoolExecutor`
plus `subprocess.run`).

Implementation notes:

- Run `_setup` and `_setup-visual` once before launching concurrent stages, so each stage does not race on `uv pip
  install`.
- Capture each stage's output independently.
- Print only pass/fail lines on success, and dump the failing stage output on failure, in the original input order
  (not completion order) so the agent's reading experience matches the existing serial recipe.
- Keep stage names stable so agents can identify the failure quickly.
- Cap concurrency at `min(nproc, N_stages)` so the parallel test run that follows is not starved.

Expected result:

- Save roughly 8-11s from `just check` after the test isolation fix.

#### Sub-optimization: parallelize `sase validate`

`src/sase/main/validate_handler.py` runs `init --check` and `sdd validate` as **serial** subprocesses via
`subprocess.run`. Each invocation pays a full Python+sase import cost (~400-600ms). Switching to
`concurrent.futures.ThreadPoolExecutor` (or just two `Popen` calls with a shared `wait()`) keeps the output ordering
intact and shaves ~1s from the SASE validation stage on its own. Trivial, isolated change.

### 3. Add a Change-Aware Fast Path

This is how to make common agent turns feel much faster than 40-50s.

Possible policy:

- If only `sdd/research/**` Markdown/images changed, `just check` can exit quickly with a clear message because the
  repo memory already says running `just check` has no point for this category.
- If only Markdown changed, run changed-file Prettier and SASE validation only when relevant.
- If only YAML changed, run keep-sorted on changed YAML.
- If only Python source/tests changed, skip Markdown formatting and SDD validation unless affected files require them.
- Always provide `just check-full` as the exhaustive local/CI gate.

This should be introduced carefully because it changes the meaning of `just check`. A conservative first version can
make `just check` print the selected stages and include `just check-full` in the message when it skips broad checks.

### 4. Revisit Test Lane Details

After the home leak is fixed, the slowest tests are no longer launch-name registry scans. The remaining slow list is
mostly artifact audit tests and PNG/Textual visual tests in the 1.5-3.6s range.

Follow-up options:

- Keep `--dist=loadfile` unless a focused pass proves file-local state is safe under `--dist=load`. The one measured
  `--dist=load` run was only about 3-4s faster than `loadfile`, so it is not worth doing first.
- Consider excluding visual tests from default `just check` for non-UI changes. After the home fix this saves only about
  5-7s, but it reduces PNG dependency and renderer-noise exposure in ordinary backend changes.
- Profile artifact audit tests separately. They are intentionally scanning source trees, so the right fix may be caching
  expected symbol/path lists or reducing duplicate scans.
- Collection cost is ~7.8s wall, paid once per xdist worker — so with 16 workers it is much higher in aggregate CPU.
  Reducing top-level imports in `src/sase/__init__.py` or moving heavy imports to lazy paths could cut steady-state
  test wall time by another 1-2s. Worth a separate `pyinstrument` pass on `pytest --collect-only`.

#### Adjuncts for change-aware testing

If the change-aware fast path (Section 3) is too coarse-grained, two pytest-side adjuncts are independently useful:

- `pytest --lf` / `--ff`: cheap re-runs of last-failed tests during a debug-fix cycle. Already supported by pytest; no
  install. Could expose as `just test-lf`.
- `pytest-testmon`: tracks which tests cover which source lines and reruns only affected tests. Costs a small overhead
  on full runs and stores state in `.testmondata`. Most useful for interactive agent loops, not CI. Trial it on a
  branch before adopting; some xdist + testmon combinations have historically been fragile.

Neither replaces the broader change-aware `just check` selector — they help inside the test stage specifically.

### 5. Out of Scope but Worth Noting

- **CI vs local divergence.** GitHub Actions runs `just test-cov` (coverage enabled), not `just test`. The home-leak
  fix benefits both because the leak is in tests, not in coverage. The non-test parallelization is local-oriented but
  also helps CI. If `just check` becomes change-aware, CI should pin to `just check-full` to preserve the safety net.
- **Workspace setup tax.** `_setup` reinstalls editable deps when `mypy` is missing or `validate_editable_metadata`
  fails. The check is cheap (~200ms steady-state), but a stale workspace can add tens of seconds on first run. This is
  pre-existing and unrelated to the leak, but agents seeing a slow first `just check` after a long-idle workspace
  should know to attribute it to install, not to tests.
- **Telemetry.** None of the above is observable in CI today. A small JSON timing dump per stage (written to
  `.pytest_cache/` or similar) would let future regressions surface as data instead of as agent perception.

## Deprioritized

- Lowering xdist worker count. `SASE_PYTEST_WORKERS=8` was slower than the default 16 workers.
- Switching immediately to `--dist=worksteal`. It measured slower than `loadfile` in this workspace.
- Optimizing Ruff or mypy first. Both are already subsecond with caches.
- Setting `HOME` for the whole check command (i.e., as a Justfile env). It speeds tests but breaks `sase validate`
  because the empty home is missing generated memory and skill files. The conftest-level fix in 1a achieves the same
  test speedup without breaking the non-test stages.
- Replacing `tools/run_silent` with a more elaborate output buffer (rich, etc.). The current bash script is correct
  and minimal; the wins are in parallelism and stage selection, not output formatting.

## Proposed End State

Near-term:

```text
just check
  setup once
  non-test checks in parallel
  test lane with fixed SASE home isolation
```

Expected wall time: roughly 40-50s.

Next:

```text
just check       # change-aware local/agent gate
just check-full  # exhaustive gate for CI and explicit local confidence
```

Expected common-case wall time: single-digit seconds for docs/research/YAML-only changes, about 10-20s for many Python
changes with targeted tests, and about 40-50s when explicitly running the full suite.
