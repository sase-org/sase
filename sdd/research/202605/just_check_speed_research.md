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
`Path.home()`.

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

## Recommended Implementation Sequence

### 1. Fix SASE Home Path Isolation

This is the highest-leverage first step.

Preferred direction:

- Add or reuse one central helper for the SASE state root, for example `sase_home() -> Path`.
- Make it honor an explicit env var such as `SASE_HOME` when present, otherwise default to `Path("~/.sase").expanduser()`.
- Replace direct `Path.home() / ".sase"` path construction in the agent-name registry with that helper.
- Update `tests/conftest.py` so the autouse redirect covers the helper path and add a regression test proving
  `_registry_path()` resolves inside the fake test home.
- Audit nearby agent-name modules (`_auto.py`, `_lookup.py`, `_claim.py`, `_migration.py`, `_wipe.py`, `_resume.py`)
  because they also use `Path.home() / ".sase"`.

Expected result:

- `just test`: about 94s -> 36-38s.
- `just check`: about 50-60s after adding the unchanged non-test stages.

This also fixes a correctness issue: tests that claim to avoid real SASE state are currently observing real state.

### 2. Parallelize Independent Non-Test Stages

The non-test stages are serial today and total about 16.7s. The longest stage is `pyvision` at about 6s. A small
`tools/check` Python orchestrator could run independent checks concurrently while preserving `tools/run_silent`-style
failure output.

Safe parallel groups:

- Python formatting check, Ruff lint, mypy, pyscripts, pyvision.
- Markdown formatting check and keep-sorted lint.
- SASE validation, unless it depends on artifacts generated by another stage.

Implementation notes:

- Run `_setup` once before launching concurrent stages.
- Capture each stage's output independently.
- Print only pass/fail lines on success, and dump the failing stage output on failure.
- Keep stage names stable so agents can identify the failure quickly.

Expected result:

- Save roughly 8-11s from `just check` after the test isolation fix.

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

## Deprioritized

- Lowering xdist worker count. `SASE_PYTEST_WORKERS=8` was slower than the default 16 workers.
- Switching immediately to `--dist=worksteal`. It measured slower than `loadfile` in this workspace.
- Optimizing Ruff or mypy first. Both are already subsecond with caches.
- Setting `HOME` for the whole check command. It speeds tests but breaks `sase validate`.

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
