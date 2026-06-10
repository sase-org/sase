---
plan: sdd/tales/202606/atomic_starting_count_and_row.md
---
 When launching agents, there is a short period of time on the "Agents" tab of the `sase ace` TUI where the agent is done starting (so the "starting" agent count is decremented), but the agent has no corresponding entry shown on the agents tab (with a "RUNNING" or "WAITING" status). Can you help me make it so decrementing the "starting" agent count and showing the new agent row always happen at the same time? Make sure we don't degrade the TUI's performance too much.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
 