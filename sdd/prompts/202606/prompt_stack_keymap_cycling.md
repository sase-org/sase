---
plan: sdd/tales/202606/prompt_stack_keymap_cycling.md
---
 #fork:9e.f1.f2  Can you now help me make sure that all four of these keymaps support cycling? Some
examples:

- When trying to move the top prompt input widget up a level with the `<ctrl+shift+h>` keymap, the current prompt input
  widget should be moved to the very bottom of the stack.
- When the bottom prompt input widget is selected, but the user tries to navigate to the below prompt input widget using
  the `<ctrl+l>` keymap, then the top prompt input widget in the stack should be selected.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
