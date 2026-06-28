---
plan: sdd/tales/202606/update_check_startup_toast.md
---
 Can you help me out with a lightweight way of periodically checking the latest versions of sase, sase-core, and all of sase's plugin repos that are currently installed? If any of the installed versions are out of date, show a nice toast to the user when they first start the TUI (remind them that they can reach the "Updates" tab of the "SASE Admin Center" panel by pressing `#5` (try to add some protection to make sure that toast message doesn't go out-of-date if/when the "Updates" tab's placement is changes--i.e. if a tab with a name that starts with a letter sorted before "U").

I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 