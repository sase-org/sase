---
create_time: 2026-03-30 12:06:04
status: done
prompt: sdd/prompts/202603/fix_neovim_plugin_errors.md
---

# Plan: Fix Neovim Plugin Errors

## Problem

Three startup errors in Neovim 0.12.0:

1. `nvim-treesitter.configs` module not found
2. `telescope` module not found in telescope-dap.nvim init
3. `overseer.vscode` module not found

## Root Cause Analysis

**Lazy.nvim has a corrupted installation state.** Investigation reveals:

- **17 plugins** stuck as stale `.cloning` lock files (0-byte regular files) — including nvim-treesitter and
  telescope.nvim. These represent failed/interrupted clones.
- **Installed plugins have deleted files** — overseer.nvim (29 deleted files) and nvim-treesitter-textobjects (23
  deleted files) both have working directories where lua source files were removed.

This means the three user-visible errors are symptoms of a broader installation corruption.

**Additionally**, there are config-level issues that exist independently of the corruption and will surface once plugins
are reinstalled:

- **treesitter.lua**: Uses the removed `require("nvim-treesitter.configs").setup()` API. The new
  nvim-treesitter-textobjects API requires `require("nvim-treesitter-textobjects").setup()` and explicit keymap
  functions instead of declarative config tables.
- **dap/init.lua**: telescope-dap.nvim calls `require("telescope")` in `init` (runs before plugins load), causing
  failure even when telescope IS installed.
- **overseer.lua**: Pinned to version `"1.6.0"` but lock file has commit `a219444` (post-v2.0). In this version,
  `overseer.wrap_template` was deleted (March 28, 2025), breaking the custom `make_targets.lua` template that depends on
  it.

## Plan

### Phase 1: Fix lazy.nvim installation state

Clean the corrupted lazy plugin directory and let lazy.nvim re-clone everything:

```bash
# Remove stale .cloning lock files
rm ~/.local/share/nvim/lazy/*.cloning

# Restore deleted files in corrupted plugin working directories
cd ~/.local/share/nvim/lazy/overseer.nvim && git checkout .
cd ~/.local/share/nvim/lazy/nvim-treesitter-textobjects && git checkout .
```

Then on next Neovim launch, `:Lazy install` will clone the missing plugins. The `lazy-lock.json` preserves exact commit
hashes so versions are deterministic.

### Phase 2: Fix treesitter.lua config

**File**: `~/.local/share/chezmoi/home/dot_config/nvim/lua/plugins/treesitter.lua`

The old API (`require("nvim-treesitter.configs").setup()`) bundled treesitter core config AND textobjects config in one
call. The new API splits them:

**nvim-treesitter plugin spec**:

- Keep `init` for keymaps (`<leader>iii`, `<leader>iit`) and language registration
- Move `ensure_installed` to `opts` (lazy.nvim passes it to the plugin setup)
- Remove `highlight`, `indent`, `matchup` from the setup call (built-in to Neovim 0.12)

**nvim-treesitter-textobjects plugin spec**:

- Move from declarative config tables to explicit `require("nvim-treesitter-textobjects").setup()` call with new option
  format (`select.lookahead`, `move.set_jumps`, etc.)
- Replace declarative keymap tables (`keymaps = {["af"] = "@function.outer"}`) with explicit `vim.keymap.set` calls
  using functions like
  `require("nvim-treesitter-textobjects.select").select_textobject("@function.outer", "textobjects")`
- Same for move (`goto_next_start`, `goto_previous_start`, etc.) and swap (`swap_next`, `swap_previous`)
- Update repeatable_move import path: `nvim-treesitter.textobjects.repeatable_move` ->
  `nvim-treesitter-textobjects.repeatable_move`

### Phase 3: Fix telescope-dap loading order

**File**: `~/.local/share/chezmoi/home/dot_config/nvim/lua/plugins/dap/init.lua`

For the telescope-dap.nvim plugin spec (line ~128-149):

- Add `"nvim-telescope/telescope.nvim"` to `dependencies`
- Change `init` to `config` so it runs after dependencies are loaded

### Phase 4: Fix overseer version pin and custom template

**File**: `~/.local/share/chezmoi/home/dot_config/nvim/lua/plugins/overseer.lua`

- Remove `version = "1.6.0"` to let it use whatever commit is in the lock file (currently post-v2.0)

**File**: `~/.local/share/chezmoi/home/dot_config/nvim/lua/overseer/template/make_targets.lua`

- Replace `overseer.wrap_template(tmpl, override, params)` pattern with standalone template definitions (each target
  gets its own `name` + `builder` table)
- Replace `vim.fn.jobstart` with `overseer.builtin.system()` to match the new built-in make template pattern
- Remove the `condition` callback (move validation into the generator, return error strings directly)

### Phase 5: Deploy and verify

```bash
chezmoi apply
```

Then launch Neovim. Lazy.nvim will clone missing plugins and the config issues should be resolved.
