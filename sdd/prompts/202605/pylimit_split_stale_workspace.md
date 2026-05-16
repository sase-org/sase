---
plan: sdd/tales/202605/pylimit_split_stale_workspace.md
---
 The sase_pylimit_split chop keeps detecting the same file multiple times in a row (last night it ran ~7 times
on the same file, for which the first run committed a fix for--that split the file and should have resulted in that file
not being picked up on the next run). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

### Additional Requirements

- The problem seems to be that we should be claiming a workspace, syncing with master, and only then run the command that produces the list of files that need to be split.