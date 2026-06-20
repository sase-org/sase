---
plan: sdd/epics/202606/linked_repos_rename_codex.md
---
 #fork:research.z.final Ok. Let's do the rename that you recommended. Let's name the new configuration field `linked_repos`, not `linked_repositories` though.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.



Make sure you plan a phase to fix the bob-cli repo's configuration too (in the ~/projects/github/bobs-org/bob-cli directory) and commit those changes using your /sase_git_commit skill.