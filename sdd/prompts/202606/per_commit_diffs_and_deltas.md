---
plan: sdd/tales/202606/per_commit_diffs_and_deltas.md
---
 We only seem to show the file "Deltas:" (a field in the agent metadata panel on the "Agents" tab of the `sase ace` TUI) for and only load diffs into file panel slots for the latest commits that agents make on a given repo (either the current or linked repos). See #sshot and the "actstat-1.3" sase agent for an example. Can you help me fix this so we load each commit's diff into the file panel (as its own file) and show file entries for all of the files that were modified by all commits in the "Deltas:" field? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 