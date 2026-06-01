---
title: Complete sase-49 lifecycle launch enforcement gap
bead_id: sase-49
create_time: 2026-06-01 14:47:49
status: done
prompt: sdd/prompts/202606/sase_49_completion_gap.md
---

# Complete sase-49 lifecycle launch enforcement gap

## Context

The `sase-49` epic is implemented across the current `sase` checkout and the matching `sase-core_10` sibling workspace.
Child bead notes point at commit hashes from prior agent handoffs, while the current branch contains rebased commits
with the `sase-49.x` IDs in their messages.

Verification found one behavioral gap: the foreground `sase run` path calls `claim_workspace(...)` but ignores a failed
`ClaimResult`. Because the lifecycle guard for archived and closed projects is enforced inside the locked claim path,
ignoring that result allows foreground work to continue after the claim was rejected.

## Plan

1. Patch `src/sase/main/query_handler/_query.py` so foreground `sase run` treats a failed workspace claim as a
   launch-blocking error and does not execute the workflow when a project is archived or closed.

2. Add a focused regression test around `run_query` that stubs the workspace claim result as failed and verifies
   workflow execution, chat persistence, and release cleanup do not run after the failed claim.

3. Run focused tests for the changed foreground-run behavior, then run the repo-required verification commands for
   touched Python code.

4. Re-check the `sase-49` child bead notes and source areas touched by the epic to confirm no additional acceptance gaps
   remain.

5. Update the epic plan frontmatter status to `done`.

6. Close the `sase-49` epic bead.
