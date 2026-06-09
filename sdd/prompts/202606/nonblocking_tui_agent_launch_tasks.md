---
plan: sdd/tales/202606/nonblocking_tui_agent_launch_tasks.md
---
 Why is there any need to block the TUI when we launch agents? Can't we use background tasks (shown in the top
right of the TUI and in the "Task Queue" panel) for whatever blocking work is required to launch an agent (even when
launching multiple agents via fanout)? Can you help me implement a solution for this? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
