---
plan: sdd/tales/202606/numeric_auto_agent_names.md
---
 We currently do not allow auto-generated agent names to use a number for their first character. I would like to
remove this constraint. Can you help me do that and make sure that the next agents that we launch use the smallest
available agent name possible For example, the next agent should be named "1" (or "0"--I forget if we start with "0" or
"1") and then "2" and so on until there are no more available (i.e. not taken by a previously run agent) 1-character or
2-character agent names left? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
