---
plan: sdd/tales/202606/prompt_stash_bundles_1.md
---
 When we currently use the `gS` or `<ctrl+g>S` keymaps in the prompt input widget, all stashes from all visible prompt input widgets are stashed individually. This results in the lose of the connection that those xprompts had with one another and risks losing important xprompt property data (that may have been loaded in the xprompt property panel at the time the user decided to stash all of the prompts). Can you help me fix this so these keymaps stash all of these prompts and their corresponding xprompt properties in a single bundle?

- These keymaps should now only ever increment the stash count by 1.
- All prompts stashed by this keymap, and the corresponding xprompt properties, should be restored at the same time when one of the `gp` / `gP` / `<ctrl+g>p` / `<ctrl+g>P` keymaps is used.
- One consequence of this is that only single prompts should be able to be selected (with the `<space>` keymap) and then bulk restored from the stash selection panel.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
