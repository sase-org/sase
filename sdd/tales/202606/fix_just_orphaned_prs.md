---
create_time: 2026-06-02 16:37:31
status: done
prompt: sdd/prompts/202606/fix_just_orphaned_prs.md
---
# Fix: `sase_fix_just` chop creates PRs not associated with any ChangeSpec

## Summary

The hourly `sase_fix_just` chop (defined in the chezmoi repo as `home/bin/executable_sase_chop_sase_fix_just`) launches
the `#!sase/fix_just` workflow, whose `fix_linters` / `fix_tests` steps spawn repair agents that open PRs via the
`#pr(...)` xprompt. Those PRs are landing on GitHub **with no associated ChangeSpec**. The root cause is a
**branch-suffix namespace collision** in SASE's `create_pull_request` commit workflow: the `_<N>` suffix is allocated
from the _ChangeSpec_ namespace but the branch is pushed into the _remote Git branch_ namespace, and the two have
drifted apart. When the chosen suffix names an already-existing remote branch, the workflow's `git push` fails, the
ChangeSpec reservation is cleaned up, and the repair agent then _manually_ pushes to the next free branch and opens the
PR itself — bypassing ChangeSpec creation entirely.

This plan fixes the suffix allocation so it is consistent with the remote branch namespace and makes the workflow
self-recover from a branch collision instead of leaving the agent to improvise, then cleans up the accumulated orphan
branches/PRs.

## Evidence (verified with `gh` and local state)

- Orphaned **open** PRs on `sase-org/sase`: **#139** (`sase_fix_just_linters_29`) and **#140**
  (`sase_fix_just_linters_31`). Neither name appears in `~/.sase/projects/sase/sase.gp` nor `sase-archive.gp`. The
  active project file contains **zero** `linters` ChangeSpecs.
- `git ls-remote` shows **31 dead `sase_fix_just_linters_*` branches** (`_1` through `_31`) but only **one** ChangeSpec
  ever existed: `sase_fix_just_linters_1` (archived) with a single recorded diff
  (`~/.sase/diffs/202605/sase_fix_just_linters-260514_025506.diff`) and a single `commit_result.json`
  (`ace-run/20260514024717`, PR #108). Every later linters run produced a branch+PR but **no** `commit_result.json`,
  **no** diff, **no** ChangeSpec.
- Smoking gun — a real run log (`~/.sase/workflows/202605/sase_ace-run-260526_212603.txt`) where the repair agent
  narrates the failure verbatim:
  > "The commit wrapper failed during push/pull bookkeeping… The generated suffix `_5` collides with an existing remote
  > branch that contains unrelated old work… The next free remote branch name is `sase_fix_just_tests_26`; I'm renaming
  > this local branch to that and pushing it… The SASE commit flow initially collided with an existing remote `_5`
  > branch, so I pushed the same commit on the next available branch."

## Root Cause (mechanism)

1. The repair agent runs `#pr(fix_just_linters)` (`xprompts/fix_just.yml`), which sets
   `SASE_COMMIT_METHOD=create_pull_request` and `SASE_PR_NAME=fix_just_linters` (`src/sase/xprompts/pr.yml`), and
   instructs the agent **not** to commit unless a finalizer says so.
2. The commit workflow pre-computes the branch/ChangeSpec name via `compute_suffixed_cl_name`
   (`src/sase/workflows/commit/changespec_operations.py`), which calls `get_next_suffix_number`
   (`src/sase/core/changespec.py`). That counter inspects **only ChangeSpec NAME entries** in the project file +
   archive. Because `fix_just` ChangeSpecs are almost never persisted (the workflow keeps failing) the namespace is
   nearly empty, so it reserves a **low** suffix (e.g. `_2`/`_5`).
3. `vcs_create_pull_request` (`src/sase/vcs_provider/plugins/_git_commit_dispatch.py`) does `git checkout -b <name>`
   then `_push_with_retry(["-u","origin",<name>])`. The **remote branch namespace is dense and monotonically growing** —
   old `sase_fix_just_*` branches are never deleted when PRs close/merge — so the reserved low-numbered branch already
   exists on the remote. The push is rejected; `_push_with_retry`'s pull-and-retry cannot reconcile the unrelated
   histories and returns failure.
4. Dispatch failure makes the workflow call `cleanup_reservation` and return `FAILED`
   (`src/sase/workflows/commit/workflow.py`) — **no ChangeSpec, no PR from the workflow.**
5. Per `pr.yml`'s "you MUST commit when the finalizer instructs" rule, the agent improvises: it finds the next free
   remote branch (`_26`, `_29`, `_31`), pushes it, and runs `gh pr create` itself — **outside** the ChangeSpec-recording
   path. Result: an orphaned PR.

This explains every observation: only `_1` (created before any remote branch existed) has a ChangeSpec; linters orphans
100% of the time (its ChangeSpec namespace stays empty, so it always reserves a colliding low number); and the chop
never stops launching because the empty-ChangeSpec guard (`CHANGESPEC_GUARD_PREFIX = "sase_fix_just_"`) never sees an
open ChangeSpec to block on. The same bug affects `fix_tests` (e.g. the orphaned `sase_fix_just_tests_26` above);
linters is simply the most visible.

## Goals

1. The `create_pull_request` branch suffix must be free in **both** the ChangeSpec namespace and the **remote branch**
   namespace, so the reserved ChangeSpec name and the pushed branch are always consistent and never collide.
2. If a collision still occurs at push time, the **workflow itself** must re-suffix (rename branch + re-reserve
   ChangeSpec) and retry, so ChangeSpec creation stays inside the tracked path. The repair agent should never need to
   hand-roll a branch/PR.
3. Restore the effectiveness of the `sase_fix_just_` ChangeSpec guard so the chop stops piling up redundant runs.
4. Clean up the 31 accumulated orphan branches / open orphan PRs.

## Proposed Changes

### 1. Make PR-branch suffix allocation remote-aware (primary fix)

- **Where:** `src/sase/workflows/commit/changespec_operations.py` (`compute_suffixed_cl_name`) feeding
  `get_next_suffix_number` (`src/sase/core/changespec.py`).
- **What:** When computing the next `_<N>`, also exclude suffixes whose branch already exists on the remote. Union the
  existing ChangeSpec names with the set of remote branch names matching `<project>_<base>_<N>` before picking the
  lowest free `N`. Reuse the existing git-provider remote-ref querying patterns (e.g.
  `git for-each-ref refs/remotes/origin/<base>_*` / `git ls-remote --heads`, as already done in
  `_git_query_ops.py::vcs_resolve_revision`).
- **Boundary note:** remote-branch enumeration is VCS-provider-specific, so the ChangeSpec-agnostic
  `compute_suffixed_cl_name` should obtain the taken-branch set through the VCS provider (a small `vcs_*` hook returning
  existing branch suffixes for a base name) rather than shelling out to git directly. Keep `get_next_suffix_number` pure
  by passing it the unioned `existing_names` set.

### 2. Self-recovering branch-collision handling at dispatch (defense in depth)

- **Where:** `vcs_create_pull_request` / `_push_with_retry` (`src/sase/vcs_provider/plugins/_git_commit_dispatch.py`)
  and the dispatch/ reservation flow in `src/sase/workflows/commit/workflow.py`.
- **What:** Distinguish a **branch-already-exists** push rejection from a real conflict. On that specific failure, bump
  to the next free suffix (consistent with change #1), rename the local branch, update `payload["name"]` + the
  reservation to match, and retry the push/PR — all within the workflow — so a ChangeSpec is always created. This
  removes the agent's need to improvise and closes the residual race between reservation time and push time.

### 3. Reduce branch accumulation (prevent recurrence)

- Ensure `fix_just` PR branches are deleted when their PRs close/merge so the remote namespace stops drifting from the
  ChangeSpec namespace. The GitHub provider already uses `gh pr close --delete-branch` for explicit closes
  (`sase_github/plugin.py`); confirm merge/cleanup paths also delete branches, and (optionally) have the chop prune
  stale `sase_fix_just_*` branches whose PRs are closed.

### 4. One-time remediation of existing orphans

- Close the open orphan PRs (#139, #140) and delete the 31 dead `sase_fix_just_linters_*` remote branches (and any
  orphaned `sase_fix_just_tests_*`). This is an operational cleanup performed with `gh`, not a code change, and should
  be done after the code fix lands so new orphans stop appearing. Surface the exact list for the user to confirm before
  deleting anything.

## Testing

- Unit test `get_next_suffix_number` / `compute_suffixed_cl_name` with a remote branch set denser than the ChangeSpec
  set: assert the chosen suffix skips every taken remote branch (regression for `_2..._31` collision).
- Workflow test (extend `tests/test_fix_just_workflow.py` / commit-workflow tests): simulate `git push -u origin <name>`
  rejected by an existing remote branch and assert the workflow re-suffixes, pushes a free branch, and **creates a
  ChangeSpec** (no orphan), rather than failing.
- Verify the chezmoi chop guard now blocks relaunch while an open `sase_fix_just_*` ChangeSpec exists (the bash
  regression suite already covers the guard in `tests/bash/sase_fix_just_chop_test.sh`).
- `just check` in the sase repo before completion.

## Out of Scope / Notes

- No change to the chezmoi chop's prompt is required for the root-cause fix; the bug is in SASE's commit workflow, not
  the chop. (`#pr(...)` usage in `xprompts/fix_just.yml` is correct.)
- The fix lives in this repo (`sase`); it is git-provider/commit-workflow logic, not Rust-core domain logic, so it stays
  on the Python/provider side of the core boundary.
- A lighter alternative considered and rejected as a _root-cause_ fix: only deleting old branches (change #3 alone). It
  reduces the collision rate but does not eliminate the namespace drift, so the orphaning bug would recur.
