---
plan: sdd/plans/202604/agents_tab_status_grouping_fix.md
---
 When grouping the "Agents" tab of the `sase ace` TUI by status, agents with the "PLAN DONE" and "EPIC CREATED"
statuses belong in the "Done" group. The "Needs Attention" group is only for agents with a status of either "PLANNING",
"FAILED", or "QUESTION". Also, agents with the "PLAN APPROVED" status should be listed under the "Running" group. Can
you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
