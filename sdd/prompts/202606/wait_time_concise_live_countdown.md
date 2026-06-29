---
plan: sdd/tales/202606/wait_time_concise_live_countdown.md
---
 When we use the `%wait` directive with the `time` keyword argument and all agents we are waiting for (if any) are done, we should show a more concise and live countdown in the roow agent row associated with that agent. For example, in #sshot, the "09y.f1" agent row should show `WAITING 1m29s` instead of `WAITING (until 14:15, 1m29s)` after this change and the `1m29s` should countdown live (every 1s). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 