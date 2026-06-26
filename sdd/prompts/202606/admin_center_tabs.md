---
plan: sdd/tales/202606/admin_center_tabs.md
---
  Can you help me make some improvements to the "SASE Admin Center"?

- Let's sort the tabs alphabetically from left-to-right.
- Each tab should have a number associated with it, starting with one and ending at six from left to right. The same number should be bound as a keymap to focus that tab when the SASE Admin Center panel is visible. So the user should be able to, for example, press `#3` to open the "SASE Admin Center" panel and jump to the 3rd tab.
- For each TUI session we should remember what tab the sase admin center panel is on. In other words if the user changes tabs on that panel and then dismisses the panel and then brings it back up later in that same `sase ace` session, then the same tab should still be focused.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! 

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 