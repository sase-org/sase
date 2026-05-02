---
create_time: 2026-04-08 01:40:43
status: done
prompt: sdd/prompts/202604/fix_xprompt_cursor.md
---

# Fix off-by-one cursor placement in sase-nvim xprompt completion

## Problem

When the user selects an xprompt from the `#@` picker, the cursor lands one character before the end of the inserted
text (`#fooba<CURSOR>r` instead of `#foobar<CURSOR>`).

## Root Cause

Race condition between synchronous cursor placement and deferred mode restoration:

1. **`insert_at_cursor`** (xprompt.lua:86-101) inserts text via `nvim_buf_set_text` and sets cursor to the last
   character (`c + #text - 1`) — runs **synchronously**
2. **Telescope's `actions.close()`** schedules deferred cursor restoration back to the pre-picker position
3. **`restore_insert_mode`** (xprompt.lua:107-127) reads cursor position inside `vim.schedule` — by this time,
   Telescope's deferred restore has already overwritten the cursor

The stale cursor position causes `restore_insert_mode` to take the wrong branch: instead of `startinsert!` (append at
EOL), it enters the `else` branch which does `startinsert` (insert before cursor char), placing the cursor one character
too early.

## Fix

Pass the post-insertion cursor target explicitly from `insert_at_cursor` to `restore_insert_mode`, so the deferred
callback uses a known-good position instead of reading a potentially stale cursor.

### Changes

#### 1. `lua/sase/xprompt.lua` — `insert_at_cursor`

- Return a table `{ row = r, col = c + #text }` (the 0-indexed position **after** the inserted text) when `insert_pos`
  is provided
- Keep the `nvim_win_set_cursor` call for immediate visual feedback (harmless if overwritten)
- For the non-`insert_pos` path (vim.ui.select fallback), return `nil` to preserve existing behavior

#### 2. `lua/sase/xprompt.lua` — `restore_insert_mode`

- Add an optional second parameter `end_pos` (`{ row: int, col: int }`, 0-indexed)
- Inside the `vim.schedule` callback:
  - If `end_pos` is provided, use it to set cursor and determine `startinsert` vs `startinsert!`
  - Otherwise, fall back to current behavior (read cursor from window)
- The key logic: if `end_pos.col >= line_len` → `startinsert!`; else → set cursor to `{ end_pos.row + 1, end_pos.col }`
  then `startinsert`

#### 3. `lua/telescope/_extensions/sase.lua` — Telescope `select_default` handler

- Capture return value from `xprompt._insert_at_cursor(...)`
- Pass it as second argument to `xprompt._restore_insert_mode(opts.origin_win, end_pos)`

#### 4. `lua/sase/xprompt.lua` — `vim.ui.select` fallback caller

- Same pattern: capture return value from `insert_at_cursor(...)`, pass to `restore_insert_mode(...)`
