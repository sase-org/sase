---
plan: sdd/tales/202605/gh_actions_failure_chop.md
---
 Can you help me write a lumberjack chop (stored in my chezmoi repo) that checks the status of the latest GitHub Actions run (e.g. using `gh`) and, if it failed, launches an agent to fix it? Make sure that we give that agent the error output from the failed action that we discovered. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)