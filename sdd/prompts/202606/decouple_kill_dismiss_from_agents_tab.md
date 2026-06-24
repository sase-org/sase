---
plan: sdd/tales/202606/decouple_kill_dismiss_from_agents_tab.md
---
 It seems like if there are background tasks that are working on dismissing or killing agents when I launch a new sase agent, then I have to wait for all of those background dismissal tasks to complete before the agent appears on the agents tab in the TUI. Killing or dismissing agents should ideally not block updates to the agents tab. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 