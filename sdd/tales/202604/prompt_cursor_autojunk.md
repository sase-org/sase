---
create_time: 2026-04-03 14:24:48
status: done
prompt: sdd/prompts/202604/prompt_cursor_autojunk.md
---

# Fix prompt input cursor misplacement after prettier auto-wrap

## Problem

When typing in the prompt input widget, prettier auto-wrap sometimes places the cursor on the wrong line after
reformatting. The user was typing "commit" and after prettier split the line, "it" ended up appended to `#plan` on line
1 instead of after `#comm` on line 2.

## Root Cause

`_map_offset` in `_text_formatting.py:84-104` uses `difflib.SequenceMatcher(None, old_text, new_text)` with the default
`autojunk=True`. For prompts longer than 200 characters, the autojunk heuristic marks common characters (spaces, vowels,
etc.) as "junk", producing fragmented opcodes with large replace blocks that span the line-break change point. The
linear cursor mapping within these blocks (`j1 + (old_offset - i1)`) is wrong because the content has been rearranged
(spaces/newlines swapped at different positions).

## Changes

### 1. Fix `_map_offset` in `_text_formatting.py`

- Add `autojunk=False` to SequenceMatcher so all characters are used as anchor points
- Change `old_offset <= i2` to `old_offset < i2` in the replace/delete branch so boundary offsets fall through to the
  next opcode (fixes an edge case when replacement sizes differ)

### 2. Add regression tests in `test_prompt_format_cursor_restore.py`

- Test with 200+ character text that triggers the autojunk heuristic, verifying cursor lands on the correct line after a
  space→newline reflow
- Test the boundary condition (cursor at exact end of a replace block with unequal sizes)

### 3. Run `just check`
