---
plan: sdd/tales/202605/plan_approval_coder_index_refresh.md
---
 When I approve a plan from the TUI now, I seem to need to do a tier 2 agent refresh (e.g. use the `,y` keymap)
in order to see the coder agent that gets launched to implement the plan. Can you help me fix this by updating the tier
1 index accordingly when a plan is approved and signaling the TUI to check the index when a coder agent is expected soon
(I think we already do something similar for STARTING agents that we know will be RUNNING / WAITING soon)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

