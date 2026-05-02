---
create_time: 2026-04-30 12:38:13
status: done
prompt: sdd/prompts/202604/deltas_current_pr.md
---
# Plan: Make DELTAS Reflect Current PR State

## Problem

The `DELTAS` ChangeSpec section is supposed to summarize the current file-level state of a PR/CL: every file that
differs from the ChangeSpec's parent/base, with line counts for the net added, modified, and removed lines.

The observed failure mode is that DELTAS can look like it describes only the previous `COMMITS` entry's modification
set. That is especially dangerous because it makes a multi-commit PR appear narrower than it really is, and downstream
workflows may treat the stale list as authoritative.

## Current Shape

Relevant code paths:

- `src/sase/ace/deltas/compute.py`
  - `compute_deltas()` resolves parent/head refs and asks the VCS provider for `diff_name_status()` plus
    `diff_line_stats()`.
  - It currently calls both methods with `(parent_ref, head_ref, cwd)`.
- `src/sase/vcs_provider/plugins/_git_query_ops.py`
  - Git provider implements those methods with `git diff --name-status -z parent..head` and
    `git diff --numstat -z parent..head`.
- `src/sase/ace/deltas/refresh.py`
  - `refresh_deltas_for_changespec()` is the best-effort compute-and-persist entry point.
- Lifecycle callers already exist after commits, ChangeSpec creation, accept, sync, rewind, and reparent/rebase.

The right invariant is not "what changed in the latest commit" and not "what changed since the last COMMITS entry was
written." It is:

> DELTAS equals the net file diff between the ChangeSpec's base tree and the current ChangeSpec head tree at refresh
> time.

## Design

### 1. Codify the Diff Semantics

Add an explicit regression around `compute_deltas()` proving cumulative behavior:

- Base has no `a.py` or `b.py`.
- First PR commit adds `a.py`.
- Second PR commit adds or modifies `b.py`.
- DELTAS after the second commit contains both `a.py` and `b.py`, with line counts from the full PR diff.

This test should use a real temporary git repo through the VCS provider where practical, because the bug is about
ref/range semantics and can be hidden by mocks.

### 2. Use Merge-Base/PR Diff Range for Git DELTAS

The Git implementation should expose current-PR diff semantics directly instead of relying on callers to know which
two-dot or three-dot form to pass.

For Git providers, change the DELTAS-oriented diff commands from:

```text
git diff parent..head
```

to an explicit merge-base range:

```text
git diff parent...head
```

or equivalently resolve `git merge-base parent head` and diff `merge_base..head`.

The explicit merge-base form is preferable if it keeps error handling and future provider behavior clearer. It also
matches the way hosted PR views usually define "current PR changes" when the base branch has moved.

Acceptance criteria:

- A file changed only on base after branch creation is not reported as a PR delta.
- A file changed in any commit on the PR branch is reported after every later refresh.
- A file added and then deleted within the branch disappears from DELTAS as net-zero.
- Line stats are computed over the same range as file status.

### 3. Avoid Stale Local Branch Tips

Check whether `resolve_revision()` can return a stale local branch when the remote branch is newer. If so, update the
Git resolution path for DELTAS refresh to prefer the currently checked-out branch when it is the target branch, and
otherwise prefer a freshly fetched remote-tracking ref over an older local branch.

This matters for manual `sase changespec sync-deltas` and TUI/background refreshes that may run outside the PR's active
workspace.

Keep this scoped:

- Do not rewrite the general checkout/branch resolution system unless needed.
- If a broader change is risky, add a small DELTAS-specific helper such as `resolve_current_changespec_head_ref()` in
  `compute.py` or a VCS provider method that has the exact semantics DELTAS needs.

### 4. Refresh Timing

Audit refresh timing after `sase commit`:

- `create_commit` dispatch must finish the commit and push/finalize before `add_commit_entry_with_id()` triggers DELTAS
  refresh.
- Resume paths must refresh after `finalize_commit()` and after idempotent COMMITS entry replay.

If tests show refresh can run before the new head is visible, move or add a final best-effort refresh at the end of
`CommitWorkflow._run_tracking_steps()` after tracking has succeeded. Keep the existing section writer atomic and
failure-tolerant.

### 5. Tests

Add focused tests before changing behavior:

- Git provider integration: `diff_name_status()` and `diff_line_stats()` return cumulative PR state across multiple
  commits.
- Regression: after two commit entries/files, DELTAS contains the net PR file list, not only the second commit's file.
- Base-advanced regression: when base changes after branch creation, DELTAS does not report base-only changes.
- Existing mapping tests for renames, copies, binary files, and line stats should continue to pass.

Likely files:

- `tests/ace/deltas/test_diff_name_status_git.py`
- `tests/ace/deltas/test_compute.py`
- Possibly `tests/test_deltas_compute.py` or a new integration-style test if the existing files get too broad.

### 6. Verification

Run the narrow tests first:

```bash
pytest tests/ace/deltas/test_compute.py tests/ace/deltas/test_diff_name_status_git.py tests/test_deltas_compute.py
```

Because this repo requires the full check after edits, run:

```bash
just install
just check
```

## Risks

- `parent...head` differs from `parent..head` when the parent branch advanced. That is intentional for PR semantics, but
  any caller that expects raw two-ref tree diff semantics should not reuse this provider method blindly.
- If other VCS providers implement `diff_name_status()` later, the contract should say "current change against base"
  rather than "literal two-dot range" so DELTAS stays portable.
- Fetching during ref resolution can be slow or flaky; keep failure behavior as preserve-existing-DELTAS.
