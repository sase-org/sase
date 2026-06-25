---
create_time: 2026-06-25 16:57:11
status: done
prompt: sdd/prompts/202606/claimed_agent_reverts_1.md
---
# Claimed Workspaces for Agent Reverts

## Goal

The Agents tab `,r` revert flow should not use the workspace directory that the selected agent originally ran in. That
directory can be claimed later by other agents and can accumulate unrelated file changes, which makes a revert fail for
reasons unrelated to the commits being reverted.

Change the revert flow so it claims a fresh short-lived workspace for each revert operation, prepares that workspace on
the relevant ChangeSpec branch, runs the preview or revert there, and releases the claim in all completion and failure
paths.

## Current Behavior

- `src/sase/ace/tui/actions/agents/_revert.py` resolves `RevertRepo` paths from the selected `Agent` row before
  submitting the tracked preview task.
- `src/sase/ace/revert_agent_preview.py` scans those paths and blocks if those worktrees are dirty.
- `src/sase/ace/revert_agent_execute.py` later reuses the preview's repo paths for the mutating `git revert`
  transaction.
- The task execution is already off the Textual event loop and tracked in the task queue, which should remain unchanged.

## Design

Introduce a small backend-owned revert workspace context instead of passing agent-run workspace paths as the authority
for git work:

- Capture immutable revert intent from the agent row:
  - project file
  - project name / basename
  - ChangeSpec name (`cl_name`)
  - agent name and optional family base
  - linked repository metadata from the agent run
  - artifact directory for the final marker
- Claim a fresh workspace with the existing RUNNING-field claim API:
  - use `claim_next_axe_workspace(project_file, workflow, os.getpid(), cl_name=...)`
  - use a distinct workflow label such as `ace(revert-agent)` so claims are identifiable
  - release with `release_workspace(project_file, workspace_num, workflow, cl_name)` in a `finally` block
- Materialize and prepare the claimed checkout before discovery or mutation:
  - materialize the primary checkout through existing workspace-provider helpers
  - clean/stash stale uncommitted state in the claimed checkout
  - checkout the selected ChangeSpec branch through the VCS provider's `resolve_revision(...)/checkout(...)` path
  - resolve suffix-linked repositories for the same workspace number, materialize them, and prepare them on the same
    branch before scanning
- Keep the TUI action lightweight:
  - it should build a revert intent and submit the existing tracked preview task
  - preview and execution remain tracked task bodies, not event-loop work
  - dedup keys should be based on stable intent data, not on the short-lived claimed workspace path

## Preview vs Execute

Preview should also use a fresh claimed workspace. Otherwise a dirty or repurposed original agent workspace can still
prevent the confirmation modal from opening.

To avoid holding a workspace claim while the confirmation modal waits for user input:

1. Preview task claims a workspace, prepares it, discovers the exact commit SHAs, builds the confirmation payload, and
   releases the workspace immediately.
2. Execute task claims a new workspace, prepares it, maps the previewed repo plans to the new claimed paths by repo
   label, revalidates the previewed SHAs, applies the revert transaction, writes the existing revert-result artifacts,
   pushes as today, and releases the workspace in `finally`.

This preserves the user's confirmation over the specific commit list shown in the modal while avoiding long-lived
modal-owned workspace claims.

## Bulk Marked-Agent Reverts

Preserve the existing bulk semantics: one transaction per repository for the combined commit set. Bulk should still
reject targets that cannot be represented by one project/branch checkout. In practice this means validating that marked
targets resolve to a single project file and a single ChangeSpec branch before submitting the preview task. The existing
multiple-workspace guard can remain as a compatibility signal, but the backend should no longer depend on those original
workspace paths for git work.

## Implementation Steps

1. Add revert intent / workspace-claim models in the `revert_agent` backend layer.
2. Add a helper that claims, materializes, prepares, and releases a revert workspace around a callback.
3. Add single-agent and bulk preview entry points that accept revert intent, claim a workspace, resolve primary plus
   eligible linked repos for that claimed workspace number, and delegate to the existing preview logic.
4. Add single-agent and bulk execute entry points that accept the preview plus intent, claim a workspace, remap repo
   plans to the newly claimed paths, and delegate to the existing execute logic.
5. Update `AgentRevertMixin` to submit those new intent-based preview/execute functions while preserving tracked-task
   behavior, modal behavior, refresh behavior, and user notifications.
6. Keep the existing low-level `preview_agent_revert(...)` and `execute_agent_revert(...)` APIs working for tests and
   direct callers that already pass explicit repo paths.

## Tests

Add focused regression coverage:

- Single-agent preview does not inspect or block on a dirty original agent workspace; it claims a new workspace and
  releases it after preview.
- Single-agent execute reverts from the claimed workspace and leaves the original agent workspace untouched.
- Release happens when preview fails, preparation fails, execute fails, and execute succeeds.
- Bulk preview/execute use one claimed workspace number and release it.
- Linked repo reverts materialize/prepare the linked checkout for the same claimed workspace number and still produce
  per-repo plans/outcomes.
- TUI task submission remains tracked and does not perform claim/materialization work in the key handler.

Run targeted tests for the revert backend and TUI action first, then run `just install` followed by `just check` after
implementation changes.

## Risks and Mitigations

- A fresh checkout may not have the ChangeSpec branch locally. Mitigation: branch preparation must use the provider's
  `resolve_revision`, which fetches and can resolve remote-tracking refs before checkout.
- Linked repos may not have a matching branch. Mitigation: report that repo as blocked in the preview rather than
  silently falling back to an old workspace.
- Workspace claims can leak if exceptions bypass cleanup. Mitigation: keep claim ownership inside a context/helper with
  `finally` release, and test failure paths explicitly.
- Preview and execute happen in separate claimed checkouts. Mitigation: execute reuses the previewed commit SHAs and
  only remaps repository paths, so it does not silently include new commits that appeared after confirmation.
