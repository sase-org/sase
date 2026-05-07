---
plan: sdd/tales/202605/xprompt_lsp_definition_e2e_fix.md
---
  Jump to definition still doesn't work with our new LSP server and nvim. I was getting errors at first and then It seemed to open the right file but the buffer was empty (maybe it used a relative path when it should have used an absolute one?). Can you try to fix this again, but this time end-to-end test your solution properly so you're certain that it's actually fixed?  Jump to definition needs to work for every xprompt, even built-in xprompts and xprompts defined by plugins.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
