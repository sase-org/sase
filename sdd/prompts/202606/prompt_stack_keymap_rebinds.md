---
plan: sdd/tales/202606/prompt_stack_keymap_rebinds.md
---
 #fork:9e.f1.f2.f1  It doesn't seem like any of these four keymaps actually work. I'm thinking
this is because the triggers we've chosen do not actually get detected in the terminal.

- Can you help me change the `<ctrl+h>` and `<ctrl+l>` keymaps to `K` and `J`, respectively, and make them available
  only in normal mode? This means that we will need to give up the `J` (join) vim-behavior in normal mode, which I am
  fine with.
- Also, can you change the `<ctrl+shift+h>` and `<ctrl+shift+l>` keymaps to the up and down arrow keys, respectively.
- Finally, can you change the `<ctrl+shift+->` keymap, which activates/deactivates the xprompt property panel to
  `<ctrl+shift+=>`.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
