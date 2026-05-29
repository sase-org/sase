---
plan: sdd/tales/202605/notification_tabs.md
---
 We currently support multiple tabs on the notification panel in the TUI but we also split each tab's notifications up by status. Can you help me stop splitting up each tab by status and instead organize notifications only by tabs?

- Plans and question notifications should go in a new "HITL" tab.
- Errors should go in a new "Errors" tab.
- Make sure other, existing tabs use a capital letter for the first character in their title (e.g. convert "done" to "Done").

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
