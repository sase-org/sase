---
create_time: 2026-04-18 00:26:03
status: done
prompt: sdd/prompts/202604/g_auto_expand_file.md
---

# Plan: Auto-expand trimmed file panel before `G` scroll-to-bottom

## Problem

On the Agents tab, when the file panel content is **trimmed** (only the first page of lines is shown with a "▾ N more
lines below" indicator), pressing `G` (`scroll_to_bottom`) only scrolls to the bottom of the _visible_ (trimmed) portion
— not to the actual end of the file. The user must first press `=` (`equals_sign` → `show_all_file_lines`) to remove the
trim, and only then can `G` reach the true bottom.

> **Assumption.** The user's reference to "the `+` keymap" maps to the existing `equals_sign` (`=`) keymap bound to
> `show_all_file_lines` in `src/sase/default_config.yml:74` — the only keybound "expand the file panel" action. `+` and
> `=` share the same physical key, and the bound action removes trimming so that `G` reaches the actual bottom. If the
> user instead meant a one-page expansion (`expand_by_page`), we would need to loop until untrimmed instead of calling
> `show_all_lines` once. Worth confirming, but `show_all_file_lines` is the natural pairing for `G`.

## Root cause

`action_scroll_to_bottom()` in `src/sase/ace/tui/actions/navigation/_basic.py:176-192` resolves the active scroll
container via `_get_agent_detail_scroll_id()` and calls `scroll_end(animate=False)`. When the active container is
`#agent-file-scroll` and the file panel is trimmed, the container's max scroll position corresponds to the trimmed
content — so `scroll_end` stops at the indicator line, not the file's true last line.

A precedent for this kind of auto-expansion already exists in the same file: `action_scroll_detail_down`
(`_basic.py:90-118`) auto-expands the file by one page when `Ctrl+D` is pressed at the bottom of trimmed content. We
need the analogous behavior for `G`, but expanding _all_ lines (not just one page) since `G` semantically means "jump to
the end."

## Changes

### 1. Auto-expand trimmed file content in `action_scroll_to_bottom`

**File:** `src/sase/ace/tui/actions/navigation/_basic.py` (function at line 176)

In the `current_tab == "agents"` branch, after resolving `scroll_id` via `_get_agent_detail_scroll_id()`:

- If `scroll_id == "#agent-file-scroll"`, query `AgentDetail` and check `agent_detail.is_file_trimmed()`.
- If trimmed, call `agent_detail.show_all_file_lines()` to remove the trim, then schedule the
  `scroll_container.scroll_end(animate=False)` via `self.call_after_refresh(...)` so the scroll happens _after_ the
  panel re-renders with full content (otherwise `scroll_end` will use the pre-expansion `max_scroll_y`).
- Otherwise, fall through to the existing `scroll_end(animate=False)` call.

The `AgentDetail` helpers (`is_file_trimmed`, `show_all_file_lines`) already exist
(`src/sase/ace/tui/widgets/agent_detail.py:295-307`); no new widget API is needed.

### 2. Leave `g` (`scroll_to_top`) alone

`scroll_to_top` does not need a counterpart change: the top of the trimmed view _is_ the top of the file (line 1), so
`scroll_home()` already does the right thing.

### 3. Other tabs unaffected

The Axe and ChangeSpecs branches do not have a trim concept and remain unchanged.

## Out of scope

- Adding a dedicated `+` keymap for `expand_by_page` (one-page expansion). This is a separate question — the user's
  request is specifically about making `G` behave correctly, not about introducing new keybindings.
- Changing `Ctrl+D` auto-expand semantics. The existing one-page expansion at the bottom of trimmed content is
  intentional ("vim-style half-page scroll, expanding gradually") and complements the new "jump straight to end"
  behavior of `G`.
- Help-modal copy. The `G` description ("Scroll to bottom") still describes the user-visible effect accurately.

## Verification

1. Open `sase ace`, switch to the Agents tab, select an agent whose diff is large enough to be trimmed (the file panel
   shows "▾ N more lines below").
2. Without first pressing `=`, press `G`. The file panel should now show all lines and the viewport should be scrolled
   to the last line of the file.
3. Confirm `G` on a non-trimmed file panel still scrolls to the bottom (no regression).
4. Confirm `G` on the Axe and CLs tabs is unchanged.
5. Run `just check`.
