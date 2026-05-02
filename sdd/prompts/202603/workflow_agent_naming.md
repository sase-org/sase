---
plan: sdd/tales/202603/workflow_agent_naming.md
---
We start multiple agents under the same workflow when agents create plans or ask questions or when the user gives
feedback on a plan. This works well mostly, but there is a problem with agent names.

- We seem to try to give subsequent agents under the same workflow the same agent name as the original agent. This is
  NOT correct.
- Instead, we should give the containing workflow the oringal name, and give each child agent the name `<name>.<N>`,
  where `<name>` is the original name and `<N>` is a positive integer which should start at 1 and increment by 1 for
  every subsequent agent step.
- I'm not sure if we support naming workflow entries right now. So this might be something you need to flesh out. Keep
  in mind that, when a workflow only contains a single agent, the workflow and the agent MUST have the same name. If a
  workflow entry contains multiple child agents, however, then each subsequent agent should be automatically given an
  agent name of the form `<name>.<N>`.

Think this through thoroughly and create a plan using your `/sase_plan` skill.
