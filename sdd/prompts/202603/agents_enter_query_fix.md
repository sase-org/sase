---
plan: sdd/tales/202603/agents_enter_query_fix.md
---
When using the `<enter>` keymap on the "Agents" tab of the `sase ace` TUI, if the ChangeSpec is not matched by the
current search query on the "CLs" tab, we should change the search query to `project:<project>`. Can you help me fix
this? We do this elsewhere in the codebase, so re-use that code if possible. Think this through thoroughly and create a
plan using your `/sase_plan` skill before making any file changes.
