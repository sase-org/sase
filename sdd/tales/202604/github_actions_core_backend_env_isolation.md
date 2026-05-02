---
create_time: 2026-04-29 12:36:17
status: done
prompt: sdd/prompts/202604/github_actions_core_backend_env_isolation.md
---
# Diagnose and Fix GitHub Actions Core Backend Test Failure

## Problem

GitHub Actions is failing in the core facade tests with `RustBackendUnavailableError` while running `just test-cov`. The
reported failure is in a test that exercises query facade behavior under `SASE_CORE_BACKEND=rust`, and local
reproduction shows the broader issue: the test process can inherit `SASE_CORE_BACKEND=rust` from the outer environment.
That makes tests which describe the default Python backend execute in strict Rust mode instead.

The backend dispatcher is behaving as documented: shipped Rust operations such as `parse_query`, `parse_project_bytes`,
`evaluate_query_many`, and `scan_agent_artifacts` must raise when Rust mode is selected and the optional `sase_core_rs`
binding is unavailable. The failure is therefore most likely test-environment leakage, not a production fallback bug.

## Investigation

- Install the repo dev environment with `just install` so local test commands use `.venv`.
- Reproduce the specific failing core facade test in isolation.
- Reproduce the whole `tests/test_core_facade.py` file with the inherited environment.
- Inspect `tests/conftest.py` and backend/facade code to confirm whether SASE core env vars are isolated per test.
- Check CI workflow configuration and just targets to understand how `just test-cov` runs pytest.

## Root Cause

`tests/conftest.py` clears `SASE_AGENT_*` and `SASE_ARTIFACTS_DIR`, but it does not clear core backend env vars such as
`SASE_CORE_BACKEND` or `SASE_CORE_DUAL_RUN`. If GitHub Actions or an agent environment exports `SASE_CORE_BACKEND=rust`,
tests that rely on the documented default backend silently start in Rust mode. With no `sase_core_rs` extension in the
CI venv, strict Rust-dispatched operations raise `RustBackendUnavailableError`.

## Fix Plan

1. Add per-test isolation for core backend env vars in `tests/conftest.py`.
   - Clear `SASE_CORE_BACKEND` before each test unless the test sets it explicitly.
   - Clear `SASE_CORE_DUAL_RUN` and the dual-run log override for the same reason.
   - Keep existing tests that intentionally set these vars unchanged.

2. Run focused regressions with an outer `SASE_CORE_BACKEND=rust` environment.
   - `tests/test_core_facade.py`
   - `tests/test_core_backend.py`
   - Any nearby core tests that already manipulate these env vars.

3. Run the required repo check after code changes.
   - Per repo memory, run `just check` before replying because files changed.

## Expected Outcome

The suite becomes hermetic with respect to the caller's core backend environment. Tests that intend to exercise strict
Rust mode still do so by setting `SASE_CORE_BACKEND=rust` inside the test, while default-backend tests consistently run
against Python regardless of CI or agent shell configuration.
