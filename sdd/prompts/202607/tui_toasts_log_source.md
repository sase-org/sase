---
plan: sdd/tales/202607/tui_toasts_log_source.md
---
 Can you help me add a new source to the "Logs" tab of the "SASE Admin Center" panel named "TUI Toasts" that contains the last `<N>` toasts sent to the user in the TUI?

- Pick a good number for `<N>` (maybe 100?).
- We should save toasts from the current session and previous sessions.
- Make sure it is made clear somehow which session each toast shown (when this log source is selected) was displayed in.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  