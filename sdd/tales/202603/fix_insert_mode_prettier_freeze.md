---
create_time: 2026-03-29 14:52:43
status: pending
prompt: sdd/prompts/202603/fix_insert_mode_prettier_freeze.md
---

# Fix: TUI freeze when typing in INSERT mode with large prompts

## Problem

When a large prompt is loaded into the prompt input widget and the user types in INSERT mode, the TUI freezes for
several seconds per keystroke. This is the INSERT mode counterpart to the NORMAL mode freeze fixed in commit `1b03c447`.

## Root Cause

The same `difflib.SequenceMatcher(autojunk=False)` bottleneck from the NORMAL mode freeze, but now triggered through the
INSERT mode path at `prompt_text_area.py:522`:

1. **Every printable non-space character triggers `_format_with_prettier()`** (line 516-522).
2. **`_map_offset()` calls `difflib.SequenceMatcher(None, old_text, new_text, autojunk=False)`** (line 155). This is
   O(n^2) for large texts and runs synchronously on the asyncio event loop.
3. **`autojunk=False` disables the heuristic** that would otherwise speed up matching for sequences longer than 200
   elements. A 10KB prompt has 10,000+ character elements.
4. **Result**: Each keystroke that triggers formatting blocks the event loop for seconds, freezing the TUI.

The `_formatting` guard (line 173) prevents concurrent formatting runs, so rapid typing causes formatting to be skipped
(the stale-input check at line 225 catches this). But when the user pauses even briefly, the next keystroke triggers the
full O(n^2) computation, causing a multi-second freeze.

## Fix

Two changes to `_format_with_prettier()` in `src/sase/ace/tui/widgets/prompt_text_area.py`:

### 1. Run `_map_offset` in a thread pool executor

Move the CPU-bound `_map_offset` call off the event loop using `asyncio.get_running_loop().run_in_executor()`. Compute
the cursor mapping _before_ replacing the document text, so that text replacement and cursor restoration happen together
without a visible intermediate state.

```python
# Before (blocking):
self._replace_via_keyboard(formatted, (0, 0), (last_row, last_col))
mapped = self._map_offset(text, formatted, cursor_offset)

# After (non-blocking):
loop = asyncio.get_running_loop()
mapped = await loop.run_in_executor(
    None, self._map_offset, text, formatted, cursor_offset
)

# Re-check stale input since we yielded control to the event loop
if self.text != text:
    return

self._replace_via_keyboard(formatted, (0, 0), (last_row, last_col))
```

Thread safety: `_map_offset` is a static method operating on immutable arguments (strings and an int). No shared state
is accessed.

### 2. Enable autojunk heuristic

Change `autojunk=False` to remove the parameter (defaulting to `autojunk=True`). For prose text, the autojunk heuristic
is appropriate — it marks high-frequency characters (like spaces and newlines) as "junk" for matching purposes, which
dramatically speeds up the algorithm for large sequences while still producing accurate cursor mapping for the
whitespace-rearrangement patterns that prettier produces.

### Testing

- Run existing `tests/test_prompt_format_cursor_restore.py` — cursor mapping accuracy must be preserved.
- Manually test with a large prompt (10KB+) in INSERT mode — keystrokes should be responsive.
- `just check` for lint/type/test pass.
