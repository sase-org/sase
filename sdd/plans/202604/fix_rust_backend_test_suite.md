---
create_time: 2026-04-29 19:01:43
status: done
prompt: sdd/prompts/202604/fix_rust_backend_test_suite.md
---
# Plan: Fix Rust backend test-suite hermeticity

## Problem

`just test` is failing in tests that call shipped `sase.core` facade helpers without selecting a backend. The pytest
autouse fixture currently deletes `SASE_CORE_BACKEND`, and production now defaults an unset backend to Rust. Under that
state, shipped facade operations require `sase_core_rs` to be importable and to expose each binding. If the test
environment has no extension or an older extension, backend-independent golden tests fail with
`RustBackendUnavailableError` before they can assert the Python contract.

This is not a parser/status-state-machine logic failure. The failures cluster exactly around facade operations whose
Rust bindings are classified as shipped:

- Git query helpers: `parse_git_name_status_z`, `parse_git_branch_name`, `derive_git_workspace_name`,
  `parse_git_conflicted_files`, `parse_git_local_changes`.
- Status helpers/planner: `read_status_from_lines`, `apply_status_update`, `plan_status_transition`.

## Goals

1. Keep production default Rust behavior intact.
2. Keep explicit Rust tests strict: `SASE_CORE_BACKEND=rust` with missing bindings must still raise.
3. Make backend-independent unit, golden, and provider tests pass regardless of whether a local Rust extension is
   installed, missing, or stale.
4. Preserve real-extension parity tests as optional checks that skip cleanly when the extension is unavailable or too
   old.

## Approach

1. Add a reusable pytest fixture that pins `SASE_CORE_BACKEND=python` for tests that are asserting pure helper behavior
   rather than backend selection. This fixture should also clear dual-run state so those tests do not accidentally log
   or route through Rust.
2. Apply that fixture narrowly to affected modules or tests:
   - Pure Git query facade contract tests at the top of `tests/test_core_git_query.py`.
   - Status-line golden tests in `tests/test_core_status_lines.py` and the status snapshot in
     `tests/test_core_golden.py`.
   - Provider tests whose purpose is Git command/provider behavior, not Rust dispatch.
   - Status state-machine tests whose purpose is transition behavior, not Rust planner dispatch, except tests that mock
     the planner facade directly.
   - Facade tests whose names/docstrings still describe the Python/default path should explicitly pin Python or be
     renamed if they are no longer testing the production default.
3. Leave existing explicit backend tests alone:
   - `tests/test_core_backend.py` should continue proving `DEFAULT_BACKEND is Backend.RUST`.
   - Tests that set `SASE_CORE_BACKEND=rust` and install fake/missing bindings should continue to exercise strict Rust
     semantics.
   - Real-extension parity tests should keep using `pytest.importorskip("sase_core_rs")` plus per-binding skips.
4. Update misleading comments/docstrings encountered while touching affected tests, especially statements like “Default
   backend is python,” so future failures are easier to diagnose.

## Verification

1. Reproduce a representative missing-extension state by running targeted failing tests with the Rust extension hidden
   or absent where practical.
2. Run focused pytest subsets for the modified areas:
   - `just test tests/test_core_git_query.py tests/test_core_status_lines.py tests/test_core_facade/test_status.py`
   - `just test tests/test_vcs_provider_git_query.py tests/test_vcs_provider_git_sync.py tests/ace/deltas/test_diff_name_status_git.py`
   - `just test tests/test_status_state_machine_field_updates.py tests/test_status_state_machine_transitions.py`
3. Run `just test` after the focused subsets.
4. Because this repo requires it after file changes, finish with `just check`.

## Non-goals

- Do not change `DEFAULT_BACKEND`.
- Do not make shipped Rust operations silently fall back to Python under explicit Rust mode.
- Do not require every developer test environment to have the newest local `../sase-core` build just to run Python
  contract tests.
