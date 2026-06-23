---
create_time: 2026-06-23 06:51:21
status: done
prompt: sdd/prompts/202606/agy_provider_test_isolation.md
---
# Plan: Fix flaky agy provider command-construction test

## Diagnosis

GitHub Actions failed in `tests/llm_provider/test_agy_provider_core.py::test_agy_provider_command_construction` because
the test expects the agy provider to use `Path.cwd().resolve()` for `--add-dir` and `cwd`, but `AgyProvider`
intentionally resolves its workspace from provider/project environment variables first.

The failure value:

```text
/tmp/pytest-of-runner/pytest-0/popen-gw3/test_chdir_handling_in_standal0
```

matches a pytest worker temp directory created by another test that exercises `_chdir` behavior and sets
`SASE_ACTIVE_PROJECT_DIR`. The agy provider checks `SASE_ACTIVE_PROJECT_DIR` before falling back to the current
directory, so any stale or inherited active-project environment variable can make this command-construction test assert
the wrong contract.

Local reproduction confirms the condition:

```bash
env -u CODEX_PROJECT_DIR SASE_ACTIVE_PROJECT_DIR=/tmp/fake-active \
  .venv/bin/pytest tests/llm_provider/test_agy_provider_core.py::test_agy_provider_command_construction -q
```

The production behavior is not the bug: `test_agy_provider_pins_workspace_cwd_and_add_dir` already asserts that
`SASE_ACTIVE_PROJECT_DIR` should pin both `--add-dir` and subprocess `cwd`. The flaky test is missing isolation for the
fallback-to-current-directory case.

## Implementation Plan

1. Make the fallback command-construction test explicit about its preconditions.
   - Add `monkeypatch: pytest.MonkeyPatch` to `test_agy_provider_command_construction`.
   - Clear all workspace-resolution environment variables used by `AgyProvider` before invoking it: `CODEX_PROJECT_DIR`,
     `SASE_ACTIVE_PROJECT_DIR`, `CLAUDE_PROJECT_DIR`, `QWEN_PROJECT_DIR`, `GEMINI_PROJECT_DIR`, `OPENCODE_PROJECT_DIR`,
     `SASE_GIT_WORKSPACE_DIR`, and `SASE_CD_WORKSPACE_DIR`.
   - Keep the assertion against `Path.cwd().resolve()` because this test should cover the no-env fallback path.

2. Leave production workspace resolution unchanged.
   - The provider should continue to honor project/workspace env vars for real agent runs.
   - The existing env-pinning test should remain the contract for `SASE_ACTIVE_PROJECT_DIR`.

3. Add a small local helper in the test file only if it improves readability.
   - Prefer a simple tuple of env names or a tiny helper scoped to the test module.
   - Avoid broad conftest changes unless verification shows more tests are affected, because global env scrubbing can
     change assumptions across unrelated tests.

## Verification

1. Re-run the exact failure reproduction with stale `SASE_ACTIVE_PROJECT_DIR` and `CODEX_PROJECT_DIR` unset.
2. Re-run the agy provider core test module.
3. Run `just check` because this repo requires it after file changes.

## Expected Outcome

The command-construction test becomes deterministic under xdist and CI regardless of inherited or previously mutated
workspace environment, while the agy provider keeps its intended behavior of pinning subprocesses to explicit workspace
env vars when present.
