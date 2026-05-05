---
plan: sdd/tales/202605/pylimit_split_chop_stale_pid.md
---
 I think there is a problem with the sase_pylimit_split chop defined in my chezmoi repo. Namely, it seems to incorrectly refuse to work because it thinks that another instance of the chop / agent
is running. Can you help me dig into this (look into `sase axe` logs and the agent runs that use the `#sase/pysplit` xprompt)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)