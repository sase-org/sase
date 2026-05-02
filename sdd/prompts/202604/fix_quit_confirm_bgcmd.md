---
plan: sdd/plans/202604/fix_quit_confirm_bgcmd.md
---
When I just hit `q` to quit the TUI, I was prompted to confirm because a background command was running which I ran via
the `!` keymap. This is NOT correct. We should only show this confirmation when a background "task" is running (ex: the
`Y` keymap triggers a background task that syncs the currently selected ChangeSpec). Can you help me diagnose the root
cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before
making any file changes.
