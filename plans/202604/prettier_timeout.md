---
create_time: 2026-04-04 10:45:20
status: done
---

# Plan: Fix Prompt Input Freeze from Prettier Subprocess Hang

## Problem

The prompt input widget freezes completely when typing prompts that contain complex markdown — specifically prompts with
`sase ace` snapshots containing unicode box-drawing characters (│┌─┘) inside backtick code fences. This is pathological
input for prettier's markdown parser.

The freeze occurs because `_format_with_prettier()` awaits `proc.communicate()` with **no timeout**. Since Textual
processes `_on_key` handlers sequentially per widget, a hung prettier subprocess blocks all subsequent key events for
the PromptTextArea, causing complete input freeze.

### Why the Previous Debounce Fix Was Reverted

Commit b8c79cca tried to fix per-keystroke subprocess lag by debouncing prettier with `loop.call_later()` +
`asyncio.ensure_future()`. This was reverted in 0c965820 because fire-and-forget async tasks raced with text edits,
causing unreliable behavior.

## Solution

Add a timeout to the prettier subprocess call. This is a minimal, targeted fix that prevents the freeze without
introducing debounce race conditions.

### `src/sase/ace/tui/widgets/_text_formatting.py`

Wrap `proc.communicate()` with `asyncio.wait_for()` using a 2-second timeout. On `TimeoutError`, kill the prettier
process and fall back to `_auto_wrap_line()`. Add `TimeoutError` to the exception handling alongside the existing
`FileNotFoundError`.

Specifically:

- Replace `stdout, _ = await proc.communicate(text.encode())` with a `wait_for` wrapper
- On timeout: call `proc.kill()` then `await proc.wait()` to reap the zombie, then fall back to `_auto_wrap_line()`
- Catch `(FileNotFoundError, TimeoutError)` instead of just `FileNotFoundError`
