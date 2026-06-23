---
plan: sdd/tales/202606/clear_agent_tag_meta_revert.md
---
 It seems impossible to clear the agent group name (to make an agent row move to the `(untagged)` agent list panel) of an agent on the agents tab using the `N` keymap (and pressing `<enter>` with no agent group name typed) when the agent name contains `<group_name>.`. This seems to work since the agent row is immediately moved, but it moves back its original group a moment later. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 