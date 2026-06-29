---
plan: sdd/tales/202606/update_availability_ux.md
---
 We currently periodically check for updates (every 10m) and display a toast to the user if there are updates available. Can you help me make sure that this works for dev/editable installs as well as normal published releases?

- Also even though we should only do the slow work every 10 minutes, once we know that an update is available, we should display that toast to the user every time they start up until they update.
- Finally let's start adding an appropriate icon/indicator to the top right of the TUI when updates are available. After we know that updates are available, this icon should always be present until the user updates sase.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 