---
plan: sdd/tales/202605/wait_derived_agent_names.md
---
 When we fork another agent (using the f keymap in the agents tab, for example), we automatically use an auto-generated agent name (unless an explicit name was given) that is based off of the forked agent name but with a .f<N> suffix. Can you help me start doing the same thing for auto-generated agent names of agents that are waiting (using the 'wait' directive) for a single other agent? We should use the .w<N> suffix for these agents though. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
