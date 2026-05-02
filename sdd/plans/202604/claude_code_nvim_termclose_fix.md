---
create_time: 2026-04-15 12:09:54
status: wip
prompt: sdd/prompts/202604/claude_code_nvim_termclose_fix.md
---

# Plan: Fix claude-code.nvim TermClose crash with NnnPicker

## Problem

When using `:NnnPicker` in Neovim and selecting a file, a `TermClose` autocommand in the `claude-code.nvim` plugin
crashes with `Invalid buffer id` because it calls `nvim_buf_get_name(args.buf)` without first checking that the buffer
is still valid.

NnnPicker creates a terminal buffer for the `nnn` file manager. When the user selects a file, nnn.nvim deletes its
terminal buffer and opens the selected file. The `TermClose` event fires, but by the time the `claude-code.nvim`
callback runs, the buffer referenced by `args.buf` has already been invalidated by nnn.nvim's own cleanup.

The `TermClose` handler at line 100-125 of `file_refresh.lua` has `pattern = '*'` (matching ALL terminals), so it fires
for every terminal close, not just Claude Code terminals.

## Fix

### Phase 1: Patch the plugin directly

Add a `nvim_buf_is_valid()` guard at the top of the `TermClose` callback in
`~/.local/share/nvim/lazy/claude-code.nvim/lua/claude-code/file_refresh.lua`, line 103-104:

```lua
callback = function(args)
  if not vim.api.nvim_buf_is_valid(args.buf) then
    return
  end
  local buf_name = vim.api.nvim_buf_get_name(args.buf)
```

This is a one-line guard — the rest of the callback remains unchanged. The `TermOpen` handler (line 88-90) uses
`nvim_get_current_buf()` which always returns a valid buffer during its own callback, so it does not need this fix.

### Phase 2: Submit upstream fix

Open an issue (or PR) on `greggh/claude-code.nvim` so the fix gets merged into the plugin. The user's `lazy-lock.json`
pins commit `55c0cb5` — once upstream merges the fix, updating the plugin via `:Lazy update claude-code.nvim` will
include it and the local patch becomes a no-op.

## Scope notes

- No changes to chezmoi-managed config files are needed — this is a plugin source bug, not a config issue.
- The direct patch will persist until the next `:Lazy update` of claude-code.nvim. Since lazy-lock.json pins a specific
  commit, updates only happen when explicitly triggered.
