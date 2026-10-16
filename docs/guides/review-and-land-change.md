---
title: Review and land a change
description:
  Inspect an agent's result and choose whether to commit, propose, or open a pull
  request.
---

# Review and land a change

Review the completed agent's work, then use the project's chosen workflow to record or
share the change.

## Before you start

You need a completed agent run and access to the project repository or pull request
provider. Decide whether the change should become a commit, a saved proposal, or a pull
request.

## 1. Choose how the result should land

Add the project's commit workflow to the agent prompt: `#commit` creates a commit,
`#propose` saves a diff for later, and `#pr` opens a pull request. Use a pull request
when someone should review the change before it merges; see the workflow reference for
its required inputs.

## 2. Wait for the run to finish

SASE handles the selected workflow after a SASE-launched agent finishes. On the Agents
tab, wait for both the agent and its finalizer to settle. Read the agent's final
response and inspect the recorded result before starting another run.

## 3. Inspect the change

For a pull request, review its Patch and the pull request diff, checks, and discussion.
For a commit, inspect the recorded commit and its changed files. Compare the result with
the task and check that the reported verification covers the change you requested.

If the change needs another pass, give a follow-up agent a clear correction and cite the
result you reviewed. See
[Hand a result to another agent](hand-a-result-to-another-agent.md).

## 4. Complete the review

Merge a pull request only after its review and checks are complete. A commit workflow
already records its commit on the configured branch; a proposal remains saved for you to
apply when it is ready.

## If it goes wrong

If the agent completed but no commit, proposal, or pull request appears, inspect the
finalizer status on the Agents tab and follow its error before retrying. The workflow
reference explains the result records and recovery details.

## Related

- [Commit workflows](../commit_workflows.md) — what each landing workflow records.
- [How changes land](../concepts/landing.md) — how SASE routes work into review.
