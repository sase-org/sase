---
plan: sdd/epics/202605/remove_recent_artifact_panel.md
---
   Can you help me remove all trace of the recent artifact panel? Review related sase beads and legend plan files. Make sure you remove all associated changes from all repos (ex: this one, my chezmoi repo, sase-core, etc...). Make sure you do not revert any of the unrelated changes that were made in the same time frame.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)