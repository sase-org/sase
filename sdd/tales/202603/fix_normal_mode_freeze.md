---
create_time: 2026-03-29 09:59:24
status: done
prompt: sdd/prompts/202603/fix_normal_mode_freeze.md
---

# Fix: TUI freeze when using vim motions on large prompts in NORMAL mode

## Problem

When a large prompt is loaded into the prompt input widget (e.g. via `<ctrl+i>` from prompt history), entering NORMAL
mode and using any motion (e.g. `gg`) causes the entire TUI to freeze permanently, requiring the user to kill the tmux
pane.

## Root Cause

A cascading failure in `_on_key` → `_format_with_prettier`:

1. **`_format_with_prettier()` is called on every NORMAL mode keypress** (`prompt_text_area.py:479`). This includes
   read-only motions like `gg`, `j`, `k`, etc. that don't modify text.

2. **`_replace_via_keyboard` is a no-op when `read_only=True`** (Textual 8.2.0 behavior). In NORMAL mode,
   `read_only=True`, so prettier's formatted output is silently discarded — the document text never changes.

3. **Since text never changes, `needs_format` stays True forever.** Every subsequent keypress re-triggers the full
   prettier pipeline.

4. **`difflib.SequenceMatcher(autojunk=False)` on the full text blocks the event loop.** Benchmarked at ~9 seconds for
   just ~11KB of text. This is synchronous CPU-bound work inside an async handler.

5. **Queued keypresses compound the freeze.** The user types additional keys while waiting, each one adding ~9+ seconds
   of blocked event loop time. The TUI never recovers.

## Fix

Remove the `await self._format_with_prettier()` call from the NORMAL mode path in `_on_key`.

**Why this is correct:** No NORMAL mode operation makes text longer. All text-modifying NORMAL mode operations (`d`,
`c`, `x`, `s`, `D`, `C`, `~`, `J`) delete or transform text without increasing length. Operations that enter INSERT mode
(`i`, `a`, `o`, `c`) will trigger formatting through the existing INSERT mode path when the user subsequently types
printable characters.

### Change

In `src/sase/ace/tui/widgets/prompt_text_area.py`, lines 475-480:

```python
# Before:
if self._vim_mode == "normal":
    if self._handle_normal_mode_key(event):
        event.stop()
        event.prevent_default()
        await self._format_with_prettier()
    return

# After:
if self._vim_mode == "normal":
    if self._handle_normal_mode_key(event):
        event.stop()
        event.prevent_default()
    return
```

### Testing

- `sase ace --agent` end-to-end tests: enter a large multi-line prompt, switch to NORMAL mode, verify motions like `gg`,
  `j`, `k`, `G` respond instantly.
- Verify that text entered in INSERT mode still auto-wraps correctly (the INSERT mode formatting path at lines 517-523
  is unchanged).
- Run `just check` to verify lint/type/test pass.
