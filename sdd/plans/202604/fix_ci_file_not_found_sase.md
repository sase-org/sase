---
create_time: 2026-04-24 09:49:56
status: done
prompt: sdd/prompts/202604/fix_ci_file_not_found_sase.md
---
# Fix CI `FileNotFoundError: 'sase'` in Commit Workflow Tests

## Problem Statement

GitHub Actions is failing 25 tests in `tests/test_pr_tags.py` and `tests/test_commit_workflow_changespec.py` with
`FileNotFoundError: [Errno 2] No such file or directory: 'sase'`.

These tests execute `CommitWorkflow.run()` for `create_pull_request`, which invokes pre-commit helpers before provider
dispatch.

## Root Cause Hypothesis

`CommitWorkflow.run()` calls `handle_beads(...)` for non-proposal flows. In repositories that contain `sdd/beads` or
`.beads`, `handle_beads` always executes:

- `sase bead sync` (best-effort)
- and sometimes `sase bead close <id>`

via `subprocess.run(["sase", ...])`.

When the `sase` CLI is not available on PATH in CI test environments, Python raises `FileNotFoundError` before
`subprocess.run` can return, which currently propagates and fails workflow tests that are not testing bead behavior.

## Design Goals

1. Preserve current bead behavior when `sase` is installed.
2. Keep bead operations explicitly best-effort.
3. Prevent missing-CLI crashes from leaking into commit/PR workflows.
4. Avoid broad behavior changes outside bead invocation paths.

## Proposed Implementation

1. Introduce a small internal helper in `src/sase/workflows/commit/precommit_hooks.py` for bead CLI execution, e.g.
   `_run_bead_command(args: list[str], cwd: str) -> None`.
2. In the helper, call `subprocess.run(...)` exactly as today but catch `FileNotFoundError` and return silently (or warn
   once via `print_status`) because bead handling is best-effort.
3. Replace direct bead subprocess calls in `handle_beads` with this helper for both:
   - `sase bead close <id>`
   - `sase bead sync`
4. Keep message mutation logic (`(bead_id)` injection) unchanged.

## Validation Strategy

1. Run targeted failing suites:
   - `tests/test_pr_tags.py`
   - `tests/test_commit_workflow_changespec.py`
2. Run full quality gate:
   - `just check`
3. Confirm no regressions in bead-related flow semantics (best-effort and non-blocking).

## Risks and Mitigations

- Risk: Suppressing `FileNotFoundError` could hide local setup issues.
  - Mitigation: optionally emit a warning status message while keeping workflow non-fatal.
- Risk: accidental change in when `sase bead sync` runs.
  - Mitigation: preserve existing conditions and only wrap execution path.

## Expected Outcome

CI tests stop failing due to missing `sase` executable, while existing behavior remains intact where `sase` is
installed.
