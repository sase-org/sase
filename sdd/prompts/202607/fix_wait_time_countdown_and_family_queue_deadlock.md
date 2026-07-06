---
plan: sdd/tales/202607/fix_wait_time_countdown_and_family_queue_deadlock.md
---
 The live countdown in the agent row doesn't seem to work right when using the `%wait` directive's `time` keyword argument while also waiting for running agents to finish (see #sshot). It seems like we also just never launch this WAITING agent, even after the incorrect countdown completes (or when the actual time is up!). The countdown shouldn't start until all agents that we were waiting for are finished. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  