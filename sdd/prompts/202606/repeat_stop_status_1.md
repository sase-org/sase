---
plan: sdd/tales/202606/repeat_stop_status_1.md
---
 I recently added support for a new STOP `/sase_var` skill variable that agents running in a fanout created by
the `%repeat` directive can set to have all subsequent agents in that fanout stopped (i.e. not launched). This seems to
be working but those agents are showing up as FAILED on the agents tab in the TUI. They should be showing up as STOPPED
instead. Can you help me fix this?

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
