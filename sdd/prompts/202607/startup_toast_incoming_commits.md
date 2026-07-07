---
plan: sdd/tales/202607/startup_toast_incoming_commits.md
---
 Can you help me start showing all of the new commits that will be added (from all repos) if the user updates sase in the toast that displays on startup if updates are available (see #sshot for an idea of what this toast looks like currently)?

- Make sure to separate each repo that has new commits that will be added in the toast that is displayed.
- We should only show a maximum of 20 commits. In this toast we should allow a single repo to have 20 commits if it is the only repo with commits. Otherwise we should try to truncate the commits from all repos with commits in a uniform way. In other words don't show just commits from one repo if there's actually 20 commits from sase that would be added and 20 commits that would be added to one of sase's plugin repos, for example.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  