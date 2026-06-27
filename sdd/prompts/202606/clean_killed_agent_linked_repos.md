---
plan: sdd/tales/202606/clean_killed_agent_linked_repos.md
---
 If I kill a sase agent that has made file changes in a linked repo using the appropriate workspace directory (obtained by running the `sase workspace open` command), then those file changes remain in place. This means that the next agent that runs using that same workspace number will wind up having the finalizer request a commit. I think this is causing commit finalizer failures when the agent (appropriately) refuses to commit those file changes that it did not make. Can you help me investigate this issue, confirm the root cause, and fix it? If I am correct about what's going on here, I think we can fix this by cleaning up the file changes that were made in linked repos in the same process/logic that kills the agent. Make sure this is done in the same background task so we do not block the TUI.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
