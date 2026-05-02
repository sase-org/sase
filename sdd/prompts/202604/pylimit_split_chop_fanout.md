---
plan: sdd/plans/202604/pylimit_split_chop_fanout.md
---
 It doesn't seem like our sase_pylimit_split chop, defined in my chezmoi repo, runs as many agents as it should per workflow run. It should run one agent per file that needs to be split. Can you help me diagnose the root cause
of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (matched: `chezmoi`)