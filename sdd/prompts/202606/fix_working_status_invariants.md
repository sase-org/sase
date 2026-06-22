---
plan: sdd/tales/202606/fix_working_status_invariants.md
---
 We recently added the new `WORKING` agent statuses, but we broke some invariants along the way. Namely:

- "plan" child agent rows should be marked with `TALE/PLAN APPROVED` and should keep that status forever after that.
- Root agent entries should ALWAYS have the same status of their most recently run child agent row (so, in the screenshot below, the "03e.cdx.f1" root agent row should have a status of `WORKING TALE`).

See the "03e.cdx.f1" sase agent in #sshot (shows the incorrect agent statuses) for an idea of what this looks like now. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 