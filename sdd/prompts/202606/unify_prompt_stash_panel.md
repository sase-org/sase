---
plan: sdd/tales/202606/unify_prompt_stash_panel.md
---
 #fork:03o.w1 Can you now help me unify the `gp` / `gP` keymaps (and corresponding `<ctrl+g>p` and `<ctrl+g>P` keymaps) by improving the prompt stash panel?

- We should get rid of the `gP` and `<ctrl+g>P` keymaps in the prompt input widget. The `@` keymap should use the same prompt stash panel as the prompt input widget (i.e. it should no longer default to popping restored prompts from the stash).
- The `gp` keymap should also be removed since the user should be able to use the `@` keymap from the prompt input widget in normal mode (the `<ctrl+g>p` keymap should continue to be available in normal and insert mode in the prompt input widget).
- We will use a new `<space>` keymap in the prompt stash panel as a way to mark that the selected prompt should be restored and popped from the stash.
- The user should still be able to use the `<tab>` keymap to mark prompts that should be restored but NOT popped.
- This means we will need to support two indicators for each prompt entry (one to indicate restore only and another to indicate restore and pop).

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! 