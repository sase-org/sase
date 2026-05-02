---
plan: sdd/tales/202603/retain_focus_after_name_change.md
---
When I change the status of a ChangeSpec from "Draft" to "Ready" and the ChangeSpec name is changed (the `_<N>` suffix
is removed) this causes a new ChangeSpec to be selected on the "CLs" tab of the `sase ace` TUI. Can you help me fix this
by retaining focus of the same ChangeSpec after any status change that changes the name of the ChangeSpec? Think this
through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
