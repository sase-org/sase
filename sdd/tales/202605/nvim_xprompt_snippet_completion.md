---
create_time: 2026-05-09 02:02:55
status: done
prompt: sdd/prompts/202605/nvim_xprompt_snippet_completion.md
---
# Plan: Stabilize Neovim SASE XPrompt Snippet Completion

## Problem

SASE xprompt snippet completion in Neovim is inconsistent. Sometimes typing a snippet trigger shows completion, `<C-n>`
selects an item, and `<Enter>` expands the snippet body. Other times the completion menu accepts or inserts only the
trigger/label text, and `<Enter>` inserts a normal newline instead of expanding the snippet.

The suspected area is correct: the issue is in the Neovim completion/LSP configuration around the `sase-nvim` plugin and
the chezmoi-managed `nvim-cmp` setup.

## Current Findings

- The chezmoi Neovim config uses `nvim-cmp` with LuaSnip expansion:
  - `home/dot_config/nvim/lua/plugins/cmp.lua`
  - `<CR>` confirms only when `cmp.visible()` and `cmp.get_active_entry()` are true.
  - LSP snippets are expanded through `cmp.setup({ snippet.expand = require("luasnip").lsp_expand(...) })`.
- The `sase-nvim` config in chezmoi enables the plugin with:
  - `complete.keymap = true`
  - `complete.completion_backend = "auto"`
  - `lsp.enabled = true`
- `sase-nvim` starts the SASE xprompt LSP at `FileType` time and always calls
  `vim.lsp.completion.enable(..., { autotrigger = true })` when native LSP completion is available.
- `nvim-cmp` is lazy-loaded on `InsertEnter`, so SASE native completion can be enabled before `nvim-cmp` is active.
- The SASE LSP completion items are valid snippet items; existing smoke tests already verify
  `CompletionItemKind.Snippet` and `InsertTextFormat.Snippet`.

## Root Cause Hypothesis

There are two completion frontends competing for the same SASE LSP completions:

1. Neovim's native `vim.lsp.completion` frontend, enabled by `sase-nvim`.
2. `nvim-cmp`, configured separately in chezmoi and responsible for LuaSnip expansion.

When `nvim-cmp` owns the menu, the existing `<CR>` mapping confirms the selected LSP snippet and LuaSnip expands it.
When native LSP completion owns the menu, `cmp.visible()` is false, so the `<CR>` mapping falls through and inserts a
newline. This explains why `<C-n>` can still move through/select a popup-menu item while `<Enter>` does not use the
LuaSnip expansion path.

## Fix Strategy

Make `sase-nvim` completion frontend selection explicit and avoid enabling native LSP completion in `nvim-cmp` setups.

1. Update `sase-nvim` LSP setup to support a configurable native completion mode.
   - Add an option such as `lsp.native_completion = "auto" | true | false`.
   - In `"auto"` mode, detect `nvim-cmp`/`cmp_nvim_lsp` and skip `vim.lsp.completion.enable` when cmp is present.
   - Preserve native LSP completion for users who do not use a completion plugin.
2. Update the SASE LSP client capabilities so cmp users get the normal cmp LSP capability shape when `cmp_nvim_lsp` is
   available.
   - Prefer `require("cmp_nvim_lsp").default_capabilities(...)` if it can be loaded.
   - Keep the explicit `snippetSupport = true` fallback.
3. Update the chezmoi `sase_nvim.lua` config to opt out of native completion explicitly.
   - Set `lsp.native_completion = false` so this personal config always routes interactive completion through
     `nvim-cmp` + LuaSnip.
4. Add/adjust `sase-nvim` tests for the new option.
   - Verify native completion is enabled when requested.
   - Verify native completion is skipped when disabled.
   - Verify `"auto"` skips native completion when cmp is detectable.
5. Validate:
   - Run the relevant `sase-nvim` checks/tests.
   - Run `just check` in the chezmoi repo if it exists and is the expected validation path.
   - Do not run `chezmoi apply --force` unless committing/applying is explicitly needed; report if the source change is
     made but not applied to `~/.config/nvim`.

## Expected Outcome

The SASE xprompt LSP can still provide the same snippet completion items, but only one completion frontend will own the
interactive UI in this Neovim setup. With native completion disabled for this chezmoi config, `<C-n>` and `<Enter>` go
through `nvim-cmp`, and snippet confirmation consistently expands via LuaSnip.
