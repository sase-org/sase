---
plan: sdd/plans/202604/claude_code_nvim_termclose_fix.md
---
I keep getting the following error in Neovim (my neovim config lives in my chezmoi repo) when use `:NnnPicker` and
select a file to open. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly
and create a plan using your `/sase_plan` skill before making any file changes.

```
Error in TermClose Autocommands for "*":
Lua callback: ...m/lazy/claude-code.nvim/lua/claude-code/file_refresh.lua:104: Invalid buffer id: 2096
stack traceback:
        [C]: in function 'nvim_buf_get_name'
        ...m/lazy/claude-code.nvim/lua/claude-code/file_refresh.lua:104: in function <...m/lazy/claude-code.nvim/lua/claude-code/file_refresh.lua:103>

```

### DYNAMIC MEMORY

- @.sase/memory/long-external-repos.md (matched: `chezmoi`)
