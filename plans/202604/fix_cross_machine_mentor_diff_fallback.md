---
create_time: 2026-04-04 14:10:47
status: done
---

# Plan: Fix Missing MENTORS Entries When Commit DIFF Files Are Missing Cross-Machine

## Problem Summary

`ase`/scheduler mentor profile matching currently depends on reading commit diff files referenced in `COMMITS` drawer
lines (e.g. `| DIFF: ~/.sase/diffs/...`). When a ChangeSpec is edited or consumed on a different machine, those local
artifact paths may not exist there. In that case, profile criteria that rely on `file_globs` or `diff_regexes` silently
fail to match, so no profile is added to `MENTORS`, and mentors do not run.

## Root-Cause Hypothesis

The matching flow in `mentor_profile_matching.py` only evaluates diff-based criteria by opening `commit.diff` paths on
disk. If the path is missing, it returns no diff match and continues silently. There is no fallback to VCS-backed diff
retrieval.

## Desired Behavior

If a commit DIFF artifact file is unavailable locally, mentor profile matching should still be able to evaluate
diff-based rules for the latest commit by retrieving diff text from the workspace VCS state. This should preserve
existing behavior when diff files are present and avoid regressions in single-machine workflows.

## Implementation Strategy

1. Add a resilient diff-content loader in mentor matching logic.

- Keep current behavior as primary path: read `commit.diff` when file exists.
- Add fallback path for missing/unreadable diff files using workspace+VCS provider APIs.
- Scope fallback to the latest commit being evaluated to avoid broad false positives from non-commit-specific fallback
  diffs.

2. Thread ChangeSpec context through profile-matching internals.

- Extend internal matching functions to accept optional `ChangeSpec` context needed for fallback retrieval.
- Preserve public-call compatibility for existing test helpers where possible by keeping optional parameters.

3. Keep matching semantics stable.

- Do not change amend-note matching.
- Do not change projects/first_commit logic.
- Only enhance diff-based criteria when artifact files are missing.

4. Add focused regression tests.

- New test: missing DIFF file still yields profile match via fallback diff retrieval.
- New test: fallback applies only to latest commit candidate (prevents overmatching older entries).
- Keep existing tests passing and update any affected function signatures minimally.

5. Validate end-to-end quality.

- Run `just install` (workspace requirement).
- Run targeted mentor matching tests first.
- Run full `just check` before final response.

## Risks and Mitigations

- Risk: fallback diff may not be commit-specific and could overmatch. Mitigation: restrict fallback usage to latest
  commit evaluation path.
- Risk: fallback may fail due workspace/VCS lookup issues. Mitigation: fail soft and retain current behavior (no crash).

## Success Criteria

- Cross-machine ChangeSpec with missing local DIFF artifact can still get a matching profile added to `MENTORS` when
  diff criteria should match.
- Existing mentor matching behavior remains unchanged when DIFF files are present.
- Test suite and `just check` pass.
