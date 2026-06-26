---
plan: sdd/tales/202606/context_reason_80_col_wrap.md
---
 Can you help me start wrapping the "reasons" we show in the "SASE CONTEXT" section of the agent metadata panel on the "Agents" tab of the `sase ace` TUI at 80 characters? I think we currently probably wrap at 100 or 120 characters, right? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.


### Additional Requirements

- The goal is to enforce a strict 80-column limit for the lines containing these reasons with pretty line wrappig when the reasons are too long. We care about the total rendered columns here (leading whitespace counts).