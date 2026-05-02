---
create_time: 2026-04-01 17:04:52
status: wip
prompt: sdd/prompts/202604/prettier_debounce.md
---

# Plan: Fix Prompt Input Prettier Integration (Performance + Reliability)

## Problem

The prompt input widget's prettier-based word wrap has two issues:

1. **Slow typing**: Every non-space printable character spawns a `prettier` subprocess via
   `asyncio.create_subprocess_exec`. The `_formatting` boolean gate prevents concurrent runs but doesn't debounce — each
   keystroke after prettier finishes triggers a new Node.js process. This creates perceptible input lag during normal
   typing.

2. **Wrapping doesn't trigger at the right time**: The code at `prompt_text_area.py:255-261` explicitly excludes spaces
   from triggering formatting. But space is the natural word boundary — when you type a long line and hit space, the
   line overflows visually but no wrap fires until the _next_ non-space character. This feels broken and unpredictable.

## Solution: Two-Tier Wrapping with Debounce

### Tier 1: Immediate simple wrap (cheap, on every character)

Run `_auto_wrap_line()` on every printable character including space. This is a pure-Python string operation (no
subprocess) that breaks the current line at the last space before the wrap boundary. It provides instant visual feedback
that the line has wrapped.

The original reason for excluding space ("so the user's trailing space is never consumed by the line break") is actually
wrong — when you hit space and the line overflows, breaking at that space _is_ the correct behavior. The space becomes
the line break point.

### Tier 2: Debounced prettier reflow (expensive, after typing pause)

Instead of running prettier on every keystroke, use a debounce timer (~300ms). Each keystroke resets the timer; prettier
only runs when typing pauses. This reduces subprocess spawns from per-keystroke to per-pause (typically 1-2x per
sentence instead of per-character).

Prettier provides better paragraph reflow than simple line-break wrapping (it rebalances all lines in the paragraph), so
it's still valuable — just not on every keystroke.

## Files to Change

### `src/sase/ace/tui/widgets/_text_formatting.py`

- Add `_format_timer: asyncio.TimerHandle | None` attribute stub for type checking
- Add `_schedule_prettier_format()` method: cancels any pending timer, sets a new one that calls
  `_format_with_prettier()` after 300ms
- No changes to `_format_with_prettier()` or `_auto_wrap_line()` — they already work correctly

### `src/sase/ace/tui/widgets/prompt_text_area.py`

- Add `self._format_timer = None` in `__init__`
- Replace the auto-wrap block in `_on_key()`:
  - Remove the `event.character != " "` exclusion
  - Call `_auto_wrap_line()` immediately for instant feedback
  - Call `_schedule_prettier_format()` for debounced reflow
