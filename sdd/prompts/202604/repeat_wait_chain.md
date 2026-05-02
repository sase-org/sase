---
plan: sdd/plans/202604/repeat_wait_chain.md
---
The `%repeat` directive now seems to spawn N agents at the same time. That is correct, but each agent except for the
first should wait for the previous agent to complete (via the `%wait` directive) before launching. Can you help me fix
this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
