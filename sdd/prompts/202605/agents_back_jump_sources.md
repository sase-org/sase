---
plan: sdd/tales/202605/agents_back_jump_sources.md
---
 When we use the double apostrophe key map to jump to the previous jump point (or the first row if there is no
previous jump point), we only currently look at whether the user used an apostrophe key map before. Can we also start
tracking the `,j` / `,J` keymaps and the `J` / `K` keymaps as well when we consider a previous jump point for the double
apostrophe keymap? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
