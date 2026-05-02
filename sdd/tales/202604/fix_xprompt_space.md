---
create_time: 2026-04-04 10:55:29
status: done
prompt: sdd/prompts/202604/fix_xprompt_space.md
---

# Fix: Missing space before xprompt insertion via #@ trigger

## Problem

When using the `#@` trigger in insert mode to open the xprompt picker, the selected xprompt text is inserted without the
preceding space. For example:

- Before: `#pr:fix_piw_freeze #` (cursor after `#`)
- Expected after selecting `m_opus_codex`: `#pr:fix_piw_freeze #m_opus_codex`
- Actual: `#pr:fix_piw_freeze#m_opus_codex` (space missing)

## Root Cause

The insertion path after Telescope selection relies on `nvim_put` relative to the **current cursor position**
(`insert_at_cursor` in `lua/sase/xprompt.lua:83-92`). The flow is:

1. `InsertCharPre` captures `col` and swallows the `@`
2. `vim.schedule` callback deletes the `#` via `nvim_buf_set_text`, calls `stopinsert`, opens picker
3. On selection, `_insert_at_cursor(name)` uses `nvim_put(..., "c", true, true)` in normal mode

Between step 2 and step 3, the cursor passes through several state transitions: `nvim_buf_set_text` (which doesn't
adjust cursor), `stopinsert` (insert-to-normal transition with cursor left-shift), Telescope open/close (window switches
and potential cursor save/restore). The cumulative effect is that the cursor ends up one position too far left -- on the
`e` of `freeze` rather than on the space. `nvim_put` with `after=true` then inserts between `e` and the space, pushing
the space to the trailing end of the line.

The `on_cancel` handler already avoids this class of bug by saving the exact buffer position and using
`nvim_buf_set_text` for position-exact reinsertion (`plugin/sase_xprompt.lua:66`). The success path should use the same
approach.

## Fix

Use position-exact insertion via `nvim_buf_set_text` instead of cursor-relative `nvim_put`.

### Step 1: Pass insert position through opts (`plugin/sase_xprompt.lua`)

Add `insert_pos = { row = row, col = col - 1 }` to the opts passed to `pick()`. This is the 0-indexed `(row, col)` where
the `#` was before deletion -- the exact position where the new `#name` text should be inserted.

### Step 2: Modify `insert_at_cursor` to accept optional position (`lua/sase/xprompt.lua`)

Add an optional `insert_pos` parameter. When provided:

- Use `nvim_buf_set_text(0, r, c, r, c, {text})` for direct insertion at the saved position
- Set cursor to end of inserted text with `nvim_win_set_cursor`

When not provided (e.g. `:SaseXPrompts` command), keep the existing `nvim_put` behavior unchanged.

### Step 3: Thread `insert_pos` through Telescope handler (`lua/telescope/_extensions/sase.lua`)

Pass `opts.insert_pos` as the second argument to `xprompt._insert_at_cursor(name, opts.insert_pos)` in the
`select_default` handler.

### Step 4: Thread `insert_pos` through fallback handler (`lua/sase/xprompt.lua`)

In the `vim.ui.select` fallback, pass `opts.insert_pos` to `insert_at_cursor` similarly.

### Files to modify

- `plugin/sase_xprompt.lua`
- `lua/sase/xprompt.lua`
- `lua/telescope/_extensions/sase.lua`
