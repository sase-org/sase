---
plan: sdd/tales/202605/nvim_xprompt_snippet_completion.md
---
   In nvim, sometimes when using the LSP xprompt snippets it works properly: # triggers completion, <ctrl+n> works for selection, and <enter> triggers snippet expansion. At other times, it just completes the snippet trigger and then <enter> just inserts a new line. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### Additional Requirements

- I suspect that this may be an issue with my nvim LSP / completion configuration in my chezmoi repo.