---
plan: sdd/tales/202604/kill_dismiss_all.md
---
Can you help me add a new `,X` (kill/dismiss all) keymap on the "Agents" tab of the `sase ace` TUI?

- This keymap shoould work like the `X` keymap on that tab, but it should also kill all running agents (whereas `X` just
  dismisses all dismissable agents).
- We should require the user to press `y` twice to confirm this action. After the first `y`, the y/n panel should change
  colors and the message to indicate that this is the final confirmation.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
