---
plan: sdd/tales/202606/q_keymap_quit_restart_panel.md
---
  The `Q` currently keymap stops axe (i.e. the `sase axe` command) and quits the TUI. Can you help me add the option to restart the TUI using this keymap?

- We should start triggering a new panel when `Q` is pressed instead of quitting the TUI. This panel should present the user with three options that they can select with a single key press:
  1. Quit and Stop AXE (current behavior of the `Q` keymap).
  2. Restart the TUI (i.e. close the TUI and then re-open it). This should be just like the user used the `q` keymap to quit the TUI and then re-ran the `sase ace` command.
  3. Restart the TUI and Restart AXE. This should be just like the user used the `q` keymap to quit the TUI and then ran the `sase ace --restart-axe` command.
- I don't think a mechanism for restarting the TUI exists right now so you may need to design one. Make sure you get this right.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
