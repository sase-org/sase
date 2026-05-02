---
plan: sdd/tales/202603/wait_workflow_completion.md
---
Can you help me make using `%wait:a`, using the agent name `a` as an example, work even when the agent proposed a plan
(in which case we change its name to `a.1` and create an `a.2` coder agent)? We should be able to accomplish this by
changing `sase axe` so it only allow the waiting agent to run when ALL `a.<N>` agents have completed. Think this through
thoroughly and create a plan using your `/sase_plan` skill.
