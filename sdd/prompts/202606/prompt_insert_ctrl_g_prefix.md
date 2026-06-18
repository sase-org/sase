---
plan: sdd/tales/202606/prompt_insert_ctrl_g_prefix.md
---
 We recently added support for a bunch of new keymaps, all of which are preficed with `g`, to the prompt input widget. These keymaps are only active in normal mode. Can you help me add support for all of these same keymaps in insert mode using the `<ctrl+g>` prefix instead of `g`?

- The existing `<ctrl+g>` keymap, which opens the prompt(s) in the user's editor, should be migrated to `<ctrl+g>g` (`<ctrl+g><ctrl+g>` should also work for conveiniance).
- Make sure that the same pretty hints are shown above the top prompt input widget that we show for the normal mode `g` keymaps.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
