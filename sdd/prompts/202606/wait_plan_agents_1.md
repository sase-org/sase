---
plan: sdd/tales/202606/wait_plan_agents_1.md
---
 Can you help me make sure that the `%wait` directive can wait for "plan" agents (i.e. agent child rows with the "plan" suffix) and that we treat the "PLAN" status as done? Also, in this case we should add a new `plan_file` jinja2 variable with a value equal to the file path of the plan that this agent proposed. This jinja2 variable should be available to all subsequent agents that run in the same multi-agent prompt / xprompt. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.


### Additional Requirements

- The `plan_file` jinja2 variable cannot be top-level. Instead, it should be namespaced under that agent's name. I think we already do this for some other variables, right?