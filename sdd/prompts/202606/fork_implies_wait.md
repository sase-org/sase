---
plan: sdd/tales/202606/fork_implies_wait.md
---
 I would like the `fork:<name>` xprompt to automatically imply `%w:<name>`. If any other `%w` directives are found, the agent should wait for all of the agents specified by those directives and the `<name>` agent. Can you help me implement this change? Also, all functionality that currently copied `fork` text or pre-fills the prompt input widget with it (check the sase-telegram repo for instances of this) should be updated to only ever use `fork` (never copy / pre-fill `%wait`). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
