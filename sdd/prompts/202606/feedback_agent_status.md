---
plan: sdd/tales/202606/feedback_agent_status.md
---
 Can you help me add support for a new `FEEDBACK` agent status that is used for agent child rows (and the root agent entry if that is the most recent agent child row to run) that proposed a plan tht the user left feedback on?

- Make sure to give this new agent status a distinct color.
- For example, in #sshot, the "08w--plan" agent should have (after this change has been applied) an agent status of `FEEDBACK` and the "08w--plan-0" agent (whose plan was approved by the user) should have an agent status of `PLAN APPROVED`. Also, it looks like the runtime for the "08w--plan" agent is wrong. Can you fix that too?

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 