---
plan: sdd/tales/202606/updates_tab_keymap_rework.md
---
 We currently use 3 different keymaps on the "Updates" tab of the "SASE Admin Center" panel to update sase, sase-core, or sase plugins: `S`, `u`, and `U`. Can you help me get rid of the `S` keymap, repurpose the `u` keymap, and make the `U` keymap update the selected plugin? 

- The `S` keymap is currently supposed to update anything that needs updating (sase, sase-core, or sase plugins).
- I would like to migrate this functionality to the `u` keymap, but this keymap should throw an error (as a toast) if there is nothing to update.
- The `U` keymap should only be available when the currently selected plugin needs updating.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 