---
plan: sdd/tales/202607/agents_tab_auto_approve_prefix_and_child_alignment.md
---
 Too many agent/Bash/Python rows are given the lightning bolt prefix on the "Agents" tab of the `sase ace` TUI (see #sshot for an example). Only the root agent entry and the child agent entry which contained `%auto` in its prompt should have this prefix. Also, make sure that all child rows are aligned (I think this requires some kind of fix when `%auto` is used). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 