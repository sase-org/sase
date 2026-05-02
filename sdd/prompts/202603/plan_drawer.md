---
plan: sdd/plans/202603/plan_drawer.md
---
When a coder agent that is implementing a plan created by a planner agent creates a COMMITS entry, can we start adding a
new `PLAN: <plan_file_path>` drawer under that entry? We should do this regardless of what `sase commit` commit method
type is being used. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file
changes.
