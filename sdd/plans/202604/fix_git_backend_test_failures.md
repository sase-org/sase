---
create_time: 2026-04-29 19:21:46
status: done
prompt: sdd/prompts/202604/fix_git_backend_test_failures.md
---
# Fix Git VCS Integration Test Backend Failures

## Context

`just test` is failing in `tests/test_vcs_provider_git_integration.py`:

- `test_integration_commit_on_current_branch`
- `test_integration_stash_and_clean`

Both failures are `RustBackendUnavailableError` from `sase.core.backend.dispatch`. The failing call paths are:

- `provider.get_branch_name()` -> `vcs_get_branch_name()` -> `parse_git_branch_name()`
- `provider.has_local_changes()` -> `vcs_has_local_changes()` -> `parse_git_local_changes()`

Those Git query facade helpers are classified as shipped Rust operations. Under the Phase 6F default backend, an unset
`SASE_CORE_BACKEND` means `rust`, and missing or stale Rust bindings must raise rather than fall back silently.

In this workspace, `sase_core_rs` is importable but does not expose the Git query bindings:

- `parse_git_name_status_z`
- `parse_git_branch_name`
- `derive_git_workspace_name`
- `parse_git_conflicted_files`
- `parse_git_local_changes`

Most unit and integration tests whose purpose is Git provider behavior, rather than backend selection, already pin
`python_core_backend`. The failing real-git integration file is an outlier: it exercises provider behavior and should
not depend on whatever optional Rust wheel happens to be installed in the local venv.

## Root Cause

The root cause is test-environment leakage from the default core backend into provider integration tests. The tests are
validating BareGitProvider behavior with real git commands, but they accidentally run facade parser calls under the
default Rust backend. When the local `sase_core_rs` package is stale or lacks Git query bindings, the backend contract
correctly raises before the provider assertion can run.

This is not a production fallback bug in `dispatch`: the shipped-operation strictness is intentional and pinned by
`tests/test_core_facade/test_backend_contract.py`. It is also not primarily a provider logic bug: the provider should
route through `sase.core.git_query_facade`, and backend selection is separately tested elsewhere.

## Implementation Plan

1. Pin `tests/test_vcs_provider_git_integration.py` to `python_core_backend`, matching nearby Git provider tests such as
   `tests/test_vcs_provider_git_query.py` and `tests/ace/deltas/test_diff_name_status_git.py`.

2. Keep the existing `git not available` skip behavior. Because the file currently uses a single module-level
   `pytestmark`, convert it to a list containing both:
   - `pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")`
   - `pytest.mark.usefixtures("python_core_backend")`

3. Re-run the focused failing file first:
   - `just test tests/test_vcs_provider_git_integration.py`

4. Because this repo requires full validation after file changes, run:
   - `just check`

5. If validation still fails because the local venv has stale dependencies, run `just install` as recommended by the
   workspace memory and then repeat the focused test and `just check`.

## Non-Goals

- Do not weaken `dispatch` strictness for shipped Rust operations.
- Do not reclassify Git query facade operations as unported.
- Do not require the real-git provider behavior tests to install or update `sase_core_rs`; backend parity and Rust
  binding availability are already covered by dedicated core backend tests.
