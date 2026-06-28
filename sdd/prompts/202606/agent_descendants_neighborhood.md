---
plan: sdd/tales/202606/agent_descendants_neighborhood.md
---
 #fork:09b Can you now help me improve the `~` (siblings) keymap?

- We should start showing agents that are decendents of the current agent's hood in a separate section / group, which should be listed at the top.
- For example, the agent `foo.bar.baz` is more related to `foo.bar.buz` then it is to `foo.pig`, so `foo.bar.baz` should be in this new group at the top.
- All dismissed agents that belong to this group should still be shown as siblings (unlike all other dimissed siblings) and should be able to be easily revived by the user without them needing to use the `R` keymap to go to the "Agent Restore" panel and search for the agent.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 