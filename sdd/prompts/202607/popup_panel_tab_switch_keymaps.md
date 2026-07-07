---
plan: sdd/tales/202607/popup_panel_tab_switch_keymaps.md
---
 Can you help me make sure that the `<tab>` and `<shift-tab>` keymaps work when the popup panels that are triggered by the `?` and `,?` keymaps is focused?

- These keymaps should change the TUI tab just like they do when these panels are not active.
- Make sure that when the user uses these keymaps to change tabs, the panel is updated appropriately (e.g. as if the user had pressed `?` or `,?` on that tab).

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 