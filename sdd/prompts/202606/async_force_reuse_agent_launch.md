---
plan: sdd/tales/202606/async_force_reuse_agent_launch.md
---
 We currently already run all of the work that could potentially block the TUI when launching agents in a
background task. However when we use the `%name:!<name>` syntax to overwrite an existing agent `<name>`, that takes a
while and is run on the main thread. Can you help me start running it in the same background task instead so we don't
block the TUI? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
