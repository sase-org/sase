---
plan: sdd/plans/202604/xprompt_completion.md
---
Can you help me add support to the existing `<ctrl+t>` keymap in the prompt input widget that currently triggers file
completion for completing xprompts as well? This should look just like the file completion does and should trigger when
we press `<ctrl+t>` when our cursor is to the right of a word that looks like an xprompt (e.g. starts with a `#`). Think
this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### DYNAMIC MEMORY

- @.sase/memory/long-tui-development.md (matched: `widget`, `keymap`)
- @.sase/memory/long-xprompt-system.md (matched: `xprompt`)
