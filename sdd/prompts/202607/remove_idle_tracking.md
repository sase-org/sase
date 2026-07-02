---
plan: sdd/tales/202607/remove_idle_tracking.md
---
 sase currently supports an activity tracking system that monitors when the user is idle. The main point of this system was to add support for only sending Telegram messages (via the sase-telegram plugin) when the user was away from the TUI. In practice, this has never worked right and I always use the pinned IDLE functionality (toggled via the `,I` keymap). Can you help me remove this "idle" functionality completely? Make sure that you remove all references to this functionality but also make sure that the sase-telegram integration works exactly as it did before when IDLE was pinned in the TUI.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  