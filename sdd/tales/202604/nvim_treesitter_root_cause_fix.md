---
create_time: 2026-04-01 20:29:51
status: wip
prompt: sdd/prompts/202604/nvim_treesitter_root_cause_fix.md
---

# Plan: Diagnose and Fix Cross-Machine Neovim Tree-sitter `node:range()` Crash

## Problem Summary

On one machine, Neovim 0.12 throws:

- `Decoration provider "start" (ns=nvim.treesitter.highlighter)`
- `.../vim/treesitter.lua:196: attempt to call method 'range' (a nil value)`

Earlier traces also showed:

- `.../nvim-treesitter/lua/nvim-treesitter/query_predicates.lua:141`

That line in legacy `nvim-treesitter` (`master`) uses `vim.treesitter.get_node_text(node, bufnr)` where `node` is
expected to be a single `TSNode`. In Neovim 0.12, query match behavior changed, and old predicate/directive handlers can
receive a list-like value (or non-node), which then reaches `vim.treesitter.get_range(node, ...)` and crashes at
`node:range()`.

## Root Cause Hypothesis

The failing machine is running an incompatible `nvim-treesitter` code path (legacy/master-era predicate directives)
against Neovim 0.12 Tree-sitter runtime behavior.

Contributing factors:

1. Plugin versions are not pinned in chezmoi (`lazy-lock.json` absent in tracked config), so machines can diverge in
   plugin branches/commits.
2. Existing config is written in legacy style options, while upstream `nvim-treesitter` has moved to an incompatible
   `main` rewrite for Neovim 0.12+.

## Investigation / Validation Steps

1. Confirm this exact mismatch signature by checking the failing machine’s installed `nvim-treesitter` file for
   `query_predicates.lua:141` containing `set-lang-from-info-string!` directive code.
2. Confirm plugin branch/commit (`:Lazy` or git in plugin dir) and verify whether it is legacy `master` vs rewritten
   `main`.
3. Confirm that after forcing `nvim-treesitter` to `main` and updating parsers, the `node:range()` crash disappears in
   the previously failing filetype.

## Implementation Plan

1. Update Neovim plugin spec in chezmoi to force `nvim-treesitter` onto `branch = "main"` for Neovim 0.12 compatibility.
2. Keep `build = ":TSUpdate"` so parser updates stay coupled with plugin updates.
3. Add a lightweight startup compatibility check/logging helper (non-fatal) that warns when Neovim 0.12+ is paired with
   legacy `nvim-treesitter` internals.
4. Keep `vim-matchup` Tree-sitter disabled (already attempted) but treat it as secondary; the primary fix is branch/API
   compatibility.

## Verification

1. Run chezmoi checks after edits:
   - `just check` (in `~/.local/share/chezmoi`)
2. Apply config:
   - `chezmoi apply`
3. Runtime validation in Neovim on the target machine:
   - `:Lazy sync`
   - `:TSUpdate`
   - Reopen previously failing file and confirm no Tree-sitter highlighter crash.

## Expected Outcome

The crash is removed by eliminating the Neovim 0.12 vs legacy `nvim-treesitter` query predicate mismatch and making
plugin branch selection deterministic across machines.
