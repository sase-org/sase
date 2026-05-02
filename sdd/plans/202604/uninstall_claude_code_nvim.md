---
create_time: 2026-04-15 12:14:57
status: done
prompt: sdd/prompts/202604/uninstall_claude_code_nvim.md
---

# Plan: Uninstall claude-code.nvim from Neovim config

## Problem

The `greggh/claude-code.nvim` plugin causes a `TermClose` crash when NnnPicker closes its terminal buffer. Rather than
patching the plugin, the user wants to remove it entirely.

## Context

- The Neovim config is chezmoi-managed (source at `~/.local/share/chezmoi/home/dot_config/nvim/`)
- Plugins are organized as individual files under `lua/plugins/`
- `lazy-lock.json` is NOT chezmoi-managed — it lives only at `~/.config/nvim/lazy-lock.json`
- The CodeCompanion `claude_code` adapter (in `lua/plugins/codecompanion/init.lua`) is a **separate integration** — it's
  CodeCompanion's built-in ACP adapter that talks to the `claude` CLI directly and does NOT depend on
  `claude-code.nvim`. It stays.

## Changes

### Step 1: Delete the plugin spec file

Delete `~/.local/share/chezmoi/home/dot_config/nvim/lua/plugins/claude_code.lua`.

This removes:

- The `greggh/claude-code.nvim` lazy.nvim plugin spec
- All `<localleader>a` keymaps (ClaudeCode, ClaudeCodeContinue, ClaudeCodeResume, ClaudeCodeVerbose)
- The `bb.is_goog_machine()` guard (no longer needed since the file is gone)

### Step 2: Remove the lazy-lock.json entry

Remove line 10 from `~/.config/nvim/lazy-lock.json`:

```
"claude-code.nvim": { "branch": "main", "commit": "55c0cb59828fbc3bec744288286a46f5d5750b83" },
```

### Step 3: Apply chezmoi

Run `chezmoi apply` to sync the deleted spec file to `~/.config/nvim/`.

### Post-implementation note

The user will need to run `:Lazy clean` in Neovim to remove the plugin's installed files from
`~/.local/share/nvim/lazy/claude-code.nvim/`. Lazy.nvim will prompt to confirm the removal on next launch if the lock
entry is gone but the directory still exists.
