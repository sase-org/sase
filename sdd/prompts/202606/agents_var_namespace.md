---
plan: sdd/tales/202606/agents_var_namespace.md
---
 For the new /sase_var command, we add those variables as jinja2 variables using the agent name as the variable. Can we start storing all of these agent variables for a given multi-agent xprompt in the same Jinja variable named "agents"? This variable should be a dictionary and should have keys for each agent name that corresponds with an agent that ran the `sase var` command. I think this might simplify how we inject these variables via Jinja. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
