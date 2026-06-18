---
plan: sdd/tales/202606/agent_group_auto_add.md
---
 Can you help me make it so that any sase agent named `foo` or that has a name that starts with `foo.` is automatically added to the agent group named "foo" if such a group already exists? This way we only need to use the `%g` directive explicitly in on agent prompt and then we can use the `%n` directive in subsequent prompts to name the agents accordingly to have them auto-added to the right group. This also means that agents that get auto-named using another agent's name as their prefix (like we do for `#fork` and `%wait`) will get auto-added to the same group as that other agent (which is appropriate).

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
