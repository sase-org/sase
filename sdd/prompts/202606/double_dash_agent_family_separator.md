---
plan: sdd/tales/202606/double_dash_agent_family_separator.md
---
 We currently use a single dash "-" to separate a root entry name from its family suffix (ex: "-code", "-plan", "-q"). Can you help me change this so we start using two dashes ("--") instead? Make sure to update all references. Also, make we should start failing (with a good error message) if user's try to launch an agent with an agent name containing "--" (this is reserved for agent families). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
