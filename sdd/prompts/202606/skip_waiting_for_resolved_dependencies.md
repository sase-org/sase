---
plan: sdd/tales/202606/skip_waiting_for_resolved_dependencies.md
---
 When we launch an agent, named say `foo`, that waits for another agent, say `bar`, to finish via the `%wait:bar` directive, but the `bar` agent finished running before the user launched `foo`, the agent still shows on the agents tab as "WAITING" for a few seconds. Can you help me skip WAITING in this case and just immediately start running the agent? Make sure this doesn't hurt the TUI's performance in any way. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 