---
create_time: 2026-06-23 08:46:02
status: done
prompt: sdd/prompts/202606/agy_workspace_dir_leak.md
---
# Fix flaky CI failure in `test_agy_trajectory.py` (leaked `SASE_ACTIVE_PROJECT_DIR`)

## Summary

Two tests fail intermittently in CI:

```
FAILED tests/llm_provider/test_agy_trajectory.py::test_agy_provider_extracts_tool_calls_from_trajectory_db
FAILED tests/llm_provider/test_agy_trajectory.py::test_agy_provider_trajectory_failure_is_best_effort
  - FileNotFoundError: Unable to launch Antigravity CLI executable '.../agy'. Set SASE_AGY_PATH ...
```

The error message is **misleading**. The `agy` fake binary is fine. The real failure is that
`subprocess.Popen(..., cwd=workspace_dir)` is given a `cwd` directory that **no longer exists**, which raises
`FileNotFoundError` for the _cwd_ (a `noexec:chdir` failure). `AgyProvider._run_subprocess` catches _any_
`FileNotFoundError` from `Popen` and unconditionally re-labels it as "executable not found".

The directory that doesn't exist is a leaked, since-deleted `pytest` tmp dir pointed to by the `SASE_ACTIVE_PROJECT_DIR`
environment variable, which leaks across tests inside an `xdist` worker.

## Root cause (confirmed by reproduction)

### The launch path

- `AgyProvider.invoke` computes `workspace_dir = _resolve_agy_workspace_dir()` (`src/sase/llm_provider/agy.py`).
- `_resolve_agy_workspace_dir()` returns the **first set** env var among `_AGY_WORKSPACE_ENV_VARS` =
  (`CODEX_PROJECT_DIR`, `SASE_ACTIVE_PROJECT_DIR`, `CLAUDE_PROJECT_DIR`, `QWEN_PROJECT_DIR`, `GEMINI_PROJECT_DIR`,
  `OPENCODE_PROJECT_DIR`, `SASE_GIT_WORKSPACE_DIR`, `SASE_CD_WORKSPACE_DIR`), resolved with
  `Path(value).resolve(strict=False)` — i.e. **no existence check** — otherwise falls back to `Path.cwd()`.
- `_run_subprocess` runs `subprocess.Popen(args, cwd=workspace_dir, ...)` and translates **every** `FileNotFoundError`
  into `_agy_executable_not_found_error(args[0])`, so a missing _cwd_ is reported as a missing _executable_.

### The env-var leak

- `SASE_ACTIVE_PROJECT_DIR` is set in production via **raw `os.environ[...] =`** assignments with no restore
  (intentional: the workspace pin must persist for the agent run):
  - `src/sase/xprompt/workflow_executor_utils.py` (`apply_chdir_output`)
  - `src/sase/axe/run_agent_phases.py`, `run_agent_runner.py`, `run_agent_exec_retry.py`, `run_workflow_runner.py`
- Several tests drive these code paths with a **tmp `workspace_dir`** and do **not** isolate the env var via
  `monkeypatch`, so the tmp path leaks into the worker process. Confirmed leakers (each leaves `SASE_ACTIVE_PROJECT_DIR`
  pointing at a `/tmp/pytest-.../...` dir):
  - `tests/test_axe_run_agent_runner_deferred_workspace.py`
  - `tests/test_axe_run_agent_exec_retry.py`
  - `tests/test_axe_run_agent_retry_spawn.py`
  - `tests/axe/test_run_agent_exec_attempts_integration.py`
- The shared autouse fixture `_clear_agent_env_vars` (`tests/conftest.py`) scrubs `SASE_AGENT_*`, `SASE_LINKED_REPO_*`,
  `SASE_SIBLING_REPO_*`, and a small fixed set — but **not** `SASE_ACTIVE_PROJECT_DIR` or the other workspace-pin vars.
  So the leak survives across tests.

### Why it is flaky / why only this file

- CI runs `pytest -n <N> --dist=loadfile` (`tools/run_pytest`). Whole files are pinned to one worker, but different
  files can land on different workers.
- `pytest` tmp-dir retention (default: keep the 3 most recent per worker) **deletes** the leaked tmp dir a few tests
  later.
- When `test_agy_trajectory.py` lands on a worker that previously ran a leaking test, the leaked
  `SASE_ACTIVE_PROJECT_DIR` now points to a **deleted** dir, so `AgyProvider.invoke` → `Popen(cwd=...)` fails.
  `test_agy_artifacts.py` (same fake-CLI mechanics) passes because it landed on an unpolluted worker; the helper-only
  trajectory tests pass because they never launch the subprocess.

### Reproductions (all green/exact-match locally)

1. `SASE_ACTIVE_PROJECT_DIR=/nonexistent pytest <the two tests>` → reproduces the **exact** CI error.
2. Running each confirmed leaker in-process shows `SASE_ACTIVE_PROJECT_DIR` left set to a tmp dir.
3. Full chain in one process: run a leaker → delete its tmp dir (simulating retention) → run the agy test → reproduces
   the exact CI error, with the hidden inner exception revealing the true cause:
   `FileNotFoundError: [Errno 2] No such file or directory: '<leaked tmp cwd>'`.

## Fix (layered)

### 1. Primary — stop the cross-test env leak (test isolation)

Harden the autouse environment isolation in `tests/conftest.py` so the workspace-pin env var family cannot leak across
`xdist` tests, regardless of which production path set them.

- Scrub the workspace-pin family **before and after** each test (yield-based teardown `pop`, so even raw
  `os.environ[...] =` assignments made during a test are removed): at minimum `SASE_ACTIVE_PROJECT_DIR`; preferably the
  full family also read by providers — `CODEX_PROJECT_DIR`, `CLAUDE_PROJECT_DIR`, `QWEN_PROJECT_DIR`,
  `GEMINI_PROJECT_DIR`, `OPENCODE_PROJECT_DIR`, `SASE_GIT_WORKSPACE_DIR`, `SASE_CD_WORKSPACE_DIR`.
- Implement either by extending `_clear_agent_env_vars` (matches its stated purpose of preventing launcher state from
  leaking) or by adding a small dedicated autouse fixture. Prefer a single source of truth for the var list.
- Validated in-memory: with the ambient value present (as in CI), `monkeypatch.delenv` at setup + `undo()`/`pop` at
  teardown overwrites the leaked tmp value and restores the real workspace dir; with the value absent, every test body
  still starts clean.

This is a **test-only** change and is the change that actually fixes the CI flake. It also prevents the same class of
failure for other providers that resolve these vars (e.g. Codex `CODEX_PROJECT_DIR`).

### 2. Secondary — accurate diagnostics in the provider (production)

In `AgyProvider._run_subprocess` (`src/sase/llm_provider/agy.py`), when `Popen` raises `FileNotFoundError`, distinguish
a **missing cwd** from a **missing executable** (e.g. inspect `exc.filename`, or check whether the resolved `cwd` is a
directory) and raise a distinct, accurate error in the cwd case. This ensures a future occurrence is self-explanatory
instead of sending the reader on a hunt for a missing `agy` binary.

### 3. Secondary — resolver robustness (production)

In `_resolve_agy_workspace_dir`, skip workspace-pin env values whose directory does not exist (advance to the next
candidate, ultimately `Path.cwd()`), so a stale/deleted workspace pin does not crash a real `agy` launch. This is
provider launch glue and stays Python-local (does not cross the Rust core boundary; no shared domain behavior changes).

### 4. Regression test

Add a focused test (e.g. in `tests/llm_provider/`) that sets a workspace-pin env var to a non-existent directory and
asserts `AgyProvider` either falls back to a valid cwd or raises the new accurate error — never the misleading
"executable not found". Optionally add a conftest-isolation assertion that the workspace-pin vars are scrubbed between
tests.

## Validation

- `just install` then `just check` (workspace is ephemeral; install first).
- Reproduce-then-confirm: run a known leaker file immediately followed by the two `test_agy_trajectory.py` invoke tests
  in one process; confirm they pass.
- Run the impacted subsets to guard against regressions from the env scrub: `tests/llm_provider`, `tests/axe`,
  `tests/test_axe_*`, `tests/workflows`, `tests/test_xprompt_*`, plus the Codex provider tests; then a full `just test`
  run.

## Out of scope / notes

- Do **not** change the production behavior of persisting `SASE_ACTIVE_PROJECT_DIR` / `os.chdir` during a real agent run
  — that persistence is intended. The bug is test isolation plus a misleading provider diagnostic, not the production
  env-pinning itself.
- No changes to memory files.
