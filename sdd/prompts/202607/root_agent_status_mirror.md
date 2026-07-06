---
plan: sdd/tales/202607/root_agent_status_mirror.md
---
 #fork:e Another problem I noticed with that screenshot is that the status of the root agent entry is "DONE" instead of "WAITING". The root agent entry should always have the same status as either the most recently launched running (where by "running" we mean has some agent status that indicates the agent is running--this includes more than just the literal "RUNNING" agent status) child agent row OR (if there are no running agents) the least recently launched WAITING child agent row (which should include the countdown if the `%wait` directive's `time` keyword argument was used).

Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  