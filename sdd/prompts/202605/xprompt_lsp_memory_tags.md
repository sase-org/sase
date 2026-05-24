---
plan: sdd/tales/202605/xprompt_lsp_memory_tags.md
---
 I'm receiving the following LSP warning in nvim when opening the memory/long/generated_skills.md file:

```
keywords:💡   ■ Xprompt keywords are only matched dynamically when tags include `memory`
```

The `memory` tag is added automatically to memory/long/ files. Can you help me fix this so our LSP server is aware of
this (make sure this diagnostic still triggers for all other xprompt markdown files)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
