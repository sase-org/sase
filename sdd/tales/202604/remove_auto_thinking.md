---
create_time: 2026-04-11 19:24:01
status: done
prompt: sdd/prompts/202604/remove_auto_thinking.md
---

# Plan: Stop Auto-Showing Thinking Panel in File View

## Problem

When `_panel_mode == DetailPanelMode.AUTO` (labeled "file" in the UI), the thinking panel is auto-shown as a fallback
whenever the file panel has no content. The user wants the "file" view to never show thinking — just expand the prompt
panel when there are no files.

## Key Insight

Removing auto-show-thinking from AUTO mode makes `_auto_show_thinking()` and `_thinking_auto_shown` completely dead. The
method is only ever called during AUTO mode, and the flag is only ever set inside that method. This means we can clean
up both the method and all 9+ references to the flag across two files.

## Phases

### Phase 1: Add `_expand_prompt_only()` helper to `AgentDetail`

**File: `src/sase/ace/tui/widgets/agent_detail.py`**

Add a helper that hides the file scroll and expands the prompt panel. This pattern already exists inline in several
places (e.g., `_agent_detail_panels.py:190-192`, `302-306`, and in `_auto_show_thinking` for non-agent entries).

### Phase 2: Replace all `_auto_show_thinking()` calls with `_expand_prompt_only()`

4 call sites:

1. `agent_detail.py:179` — bash/python workflow steps
2. `agent_detail.py:200` — done agents with no files/workspace
3. `_agent_detail_panels.py:189` — `_apply_panel_mode()` AUTO fallback
4. `_agent_detail_panels.py:300` — `on_file_visibility_changed()` no-file fallback

Also replace inline expand-prompt patterns at `_agent_detail_panels.py:190-192` and `302-306` with the helper.

### Phase 3: Remove dead code

With no callers left, remove:

- `_auto_show_thinking()` method and its type stub in the mixin
- `_thinking_auto_shown` attribute (init, type declaration, all reads/writes)
- Simplify `is_thinking_visible()` to just `self._panel_mode == DetailPanelMode.THINKING`
- Simplify `_update_panel_indicators()` thinking-active condition
- Simplify `on_thinking_visibility_changed()` — remove the `_thinking_auto_shown` guard and clear logic
- Simplify `on_file_visibility_changed()` — remove the auto-shown-thinking-to-file switching logic
- Simplify `update_display()` — the `_thinking_auto_shown` branch in the early return and the completed-agent
  fall-through logic can be removed

### Phase 4: Verify

`just install && just check`
