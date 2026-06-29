---
plan: sdd/tales/202606/wait_time_countdown_after_deps.md
---
 When the `%wait` directive is used with agent names and the `time` keyword argument with a relative time, which can be used in the same `%wait` directive or in separate `%wait` directives, we shouldn't start counting down until all of the agents we are waiting for have completed. But this does not seem to be how this currently operates (see #sshot). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 