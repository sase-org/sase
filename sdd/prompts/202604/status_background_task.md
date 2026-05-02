---
plan: sdd/tales/202604/status_background_task.md
---
When we change the status of a ChangeSpec using the `s` keymap on the "CLs" tab of the `sase ace` TUI and that status
transitino required checking out the corresponding PR (e.g. to rename it), sometimes it blocks the TUI for a while. Can
you help me migrate this to a background task (we recently did this for the `R` keymap)? Think this through thoroughly
and create a plan using your `/sase_plan` skill before making any file changes.
