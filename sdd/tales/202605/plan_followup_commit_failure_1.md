---
create_time: 2026-05-22 17:24:43
status: done
prompt: sdd/prompts/202605/plan_followup_commit_failure_1.md
---
# Fix Approved-Plan Coder Launch Failures

## Problem

Approving the `a2l` and `a2m` plans did not produce usable coder agents. The approval response path worked: both
original agents recorded `plan_approved=true`, `plan_action=tale`, and consumed their `plan_response.json` files.
Follow-up artifact directories were also created for `a2l-code` and `a2m-code`.

The failure happened after approval and before the coder prompt reached the model:

- `a2l-code` and `a2m-code` were left with `workflow_state.json` stuck at `status=running`, `main` step `in_progress`,
  no `done.json`, and dead parent PIDs.
- Their run logs show `sase commit for SDD files failed`, followed by prompt validation failures for
  `@sdd/tales/202605/notification_copy_path.md` and `@sdd/tales/202605/migrate_chezmoi_sibling.md`.
- The `#gh` pre-steps stashed uncommitted files before validation, so uncommitted SDD files written by the approval path
  were no longer present when the coder prompt referenced them.

## Root Cause

`handle_plan_marker()` treats a version-controlled SDD plan as committed whenever `should_commit` is true and an
`sdd_plan_path` exists. It does this even if `_commit_sdd_files()` fails. The follow-up coder prompt then prefers the
repo-relative `sdd/tales/...` path because `plan_result.commit_plan` is true and the file exists before `#gh` cleanup.

That creates a false handoff invariant:

1. The plan is written into the workspace as an uncommitted SDD file.
2. The SDD commit attempt fails.
3. Metadata and prompt construction still treat the SDD file as durable.
4. `#gh` pre-steps stash/clean the uncommitted SDD file.
5. Prompt file-reference validation aborts because `@sdd/tales/...` no longer exists.

There is also a secondary robustness issue in `run_agent_runner.py`: a `SystemExit` from prompt validation bypasses the
inner `except Exception` handler, then the completion notification path can hit `UnboundLocalError` because `runtime` is
only assigned after the normal/error path.

## Implementation Plan

1. Make SDD commit success explicit.
   - Change `commit_sdd_files_for_exec_plan()` to return a boolean indicating whether all discovered SDD files are
     safely committed or no commit was needed.
   - Preserve existing warning logging on non-zero `sase commit`, but return `False` instead of leaving callers to infer
     success from file existence.
   - Keep the no-files case as `True` or a clearly documented no-op so unrelated approvals are unaffected.

2. Use durable-plan semantics in `handle_plan_marker()`.
   - Capture the SDD commit result when `should_commit` is true.
   - Set `plan_committed` only when the plan path exists and the required commit succeeded, or when local non-versioned
     SDD commit/copy semantics make the path durable.
   - For normal coder follow-ups, set `SASE_PLAN` and build the coder prompt from the committed SDD path only when
     `plan_committed` is true. Otherwise fall back to the archived `~/.sase/plans/...` file so `#gh` cleanup cannot
     remove the referenced plan.
   - For epic/legend follow-ups, avoid handing off a repo-relative SDD path after commit failure; use the archived plan
     as the fallback rather than a volatile uncommitted SDD path.

3. Fix runner finalization after prompt-validation exits.
   - Ensure `runtime` has a default before the `try/finally`.
   - Catch `BaseException` cases that represent controlled prompt-validation exits, or otherwise make the finalizer
     robust enough to write a failure marker and notification without masking the original error.
   - Keep user-initiated kills distinct so explicit kills still avoid noisy completion notifications.

4. Add targeted regression tests.
   - Update SDD commit tests to assert success/failure return values.
   - Add a plan-followup test where `_commit_sdd_files()` fails for a tale approval and verify the coder prompt uses the
     archived plan path, `SASE_PLAN` points at the archive, and `plan_committed` is false in follow-up metadata.
   - Add or adjust tests for successful commit to keep the existing committed `sdd/tales/...` handoff behavior.
   - Add a runner/finalization test if there is an existing lightweight seam for validating `SystemExit` handling;
     otherwise keep that change minimal and verify with the existing runner-related tests.

5. Verify.
   - Run focused tests for `test_sdd_commit.py`, approved-plan follow-up tests, and runner tests touched by the
     finalizer.
   - Run `just install` if needed for this workspace.
   - Run `just check` before finishing because this change edits Python source in the main `sase` repo.

6. Cleanup/runtime state.
   - Report the stale `a2l-code` and `a2m-code` artifact state explicitly.
   - Do not mutate or dismiss historical artifacts unless asked. The already-running manual `#coder` retries (`a2p`,
     `a2q`) can continue independently.
