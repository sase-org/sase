---
create_time: 2026-04-03 13:04:22
status: done
prompt: sdd/prompts/202604/prompt_scroll_fix.md
---

# Fix: Prompt Input Widget Not Scrolling With Cursor

## Problem

The `PromptTextArea` in the ace TUI doesn't scroll to keep the cursor visible when navigating a long prompt (e.g., 97+
lines). The viewport stays fixed while the cursor moves off-screen.

## Root Cause Analysis

The issue stems from the CSS `height: auto` on the `#prompt-input` TextArea widget (`src/sase/ace/tui/styles.tcss:703`).

**How Textual's layout interacts with `height: auto` on a ScrollView:**

1. `TextArea` extends `ScrollView`, which overrides `get_content_height()` to return `self.virtual_size.height` (the
   full content height, e.g. 97 wrapped lines).
2. When `height: auto` is set, the layout engine asks for the widget's content height and tries to allocate that much
   space.
3. The parent `PromptInputBar` (a `Static` subclass) has a fixed height set by `_update_height()`, capped at
   `screen_height - 2`.
4. The TextArea ends up sized to its full virtual content height in its own layout calculations, even though the parent
   clips the visual overflow. From the TextArea's perspective, all content is "visible" — so `scroll_cursor_visible()`
   (called via `_watch_selection` on every cursor move) computes that no scrolling is needed.

**Secondary issue:** Textual's `TextArea._on_resize()` calls `_rewrap_and_refresh_virtual_size()` but does NOT call
`scroll_cursor_visible()`. So when the `PromptInputBar` height changes (via `_update_height`), the TextArea is resized
but the cursor isn't scrolled into view.

## Fix

### 1. Change TextArea CSS from `height: auto` to `height: 1fr`

**File:** `src/sase/ace/tui/styles.tcss`

Change `PromptInputBar #prompt-input` height from `auto` to `1fr`. This tells the layout engine "fill the parent's
available space" rather than "size to content." The TextArea will then have a properly constrained viewport size,
enabling its internal scrolling to work correctly.

This works because `PromptInputBar._update_height()` already dynamically sizes the parent based on content — so when
content is small, the parent is small and the TextArea fills it perfectly. When content exceeds `max_height`, the parent
caps out and the TextArea (now properly sized to the parent's bounds) scrolls internally.

### 2. Add `scroll_cursor_visible()` after resize in PromptTextArea

**File:** `src/sase/ace/tui/widgets/prompt_text_area.py`

Override `_on_resize` to call `scroll_cursor_visible()` after the parent's re-wrap. This ensures that when the
PromptInputBar height changes (growing or hitting max), the cursor remains visible.

## Verification

- Open `sase ace`, compose a prompt longer than the screen height
- Navigate with vim motions (j/k/G/gg/Ctrl+d/Ctrl+u) — viewport should follow cursor
- Type in INSERT mode past the visible area — viewport should follow
- Verify short prompts (< screen height) still render without excess whitespace
