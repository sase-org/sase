---
plan: sdd/tales/202606/operations_tab.md
---
 Can you help me merge the "Tasks" and "Logs" tabs of the "SASE Admin Center" panel into a single, new "Operations" panel?

- This panel should have two tabs: one for tasks, another for logs. See how the projects tab handles this for inspiration.
- Make sure we retain all functionality for both of these tabs. In other words the new sub tabs should work exactly like the old tabs did.
- Make sure the operations tab is sorted properly in the tab list and make sure to update the numeric keymaps on that tab appropriately.
- The "Tasks" sub-tab should be the one loaded by default when the "Operations" tab is first loaded, but we should remember which of those two sub-tabs is active throughout the session (i.e. until the user quits the TUI).

I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 