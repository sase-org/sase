---
plan: sdd/tales/202606/local_xprompt_keymaps.md
---
 Can you help me add new `gX` (normal mode) and `<ctrl+g>X` (insert mode) keymaps to the prompt input widget?

- These keymaps should save the prompt in the current prompt input widget as a local xprompt (i.e. will migrate this prompt to the `xprompts` property in the TUI's xprompt property panel--shown above the top prompt input widget).
- After triggering this keymap, the user should be prompted for a name to use for the new local xprompt (an underscore should be prepended to it automatically).
- Any Jinja2 variables that are used in the prompt should be recognized and auto added as inputs using text as the default type.
- The prompt should then be cleared from the current prompt input widget and replaced with a proper call / invocation for that local xprompt.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
