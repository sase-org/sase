---
plan: sdd/tales/202606/xprompts_enabled_skips_early_jinja_render.md
---
 The "041" sase agent just failed with the `WorkflowExecutionError: Step 'main' failed: Encountered unknown tag 'm'.` error even though the `%m` directive was used inside a `%xprompts_enabled` block. Directives shouldn't be used or validated inside of these blocks. Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 