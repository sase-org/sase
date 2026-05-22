---
create_time: 2026-05-22 14:51:49
status: done
prompt: sdd/prompts/202605/prompt_input_bar_noscreen_crash.md
---
# Fix `NoScreen` crash in `PromptInputBar._update_height`

## Problem

`sase ace` TUI crashes with `NoScreen: node has no screen` at `src/sase/ace/tui/widgets/prompt_input_bar.py:162`
immediately after the user submits a prompt to launch a new agent.

Traceback ends at:

```
screen_height = self.screen.size.height   # prompt_input_bar.py:162
```

with `node = None` inside `DOMNode.screen` — the parent chain walk found no `Screen` ancestor.

## Root cause

The bar updates its own height in response to text changes:

1. `on_text_area_changed` (line 135) calls `_schedule_height_update`.
2. `_schedule_height_update` (lines 169-172) runs `_update_height` synchronously, then schedules a second
   `_update_height` via `self.call_after_refresh(self._update_height)`. The deferred call is queued by Textual and fires
   after the next render cycle.

When the user submits a prompt, the bar is **synchronously detached** before the queued callback fires:

1. `PromptBarSubmitMixin.on_prompt_input_bar_submitted` (`actions/agent_workflow/_prompt_bar_submit.py:23`) →
   `_finish_agent_launch` → `_unmount_prompt_bar_after_submit`.
2. `_detach_prompt_bar` (`actions/agent_workflow/_prompt_bar_mount.py:189-202`) forcibly does
   `parent._nodes._remove(bar)` _then_ `bar.remove()`. The synchronous nodes removal is deliberate — the comment on
   lines 196-202 explains it prevents `DuplicateIds` if the user rapidly re-mounts the bar.
3. The pending `call_after_refresh(_update_height)` then fires. The widget's parent chain is now broken, so
   `DOMNode.screen` raises `NoScreen`.

The existing `if not self.is_mounted: return` guard at line 158 doesn't help: `is_mounted` reflects Textual's async
mount/unmount pipeline, which has not caught up with the synchronous `_nodes._remove` performed by `_detach_prompt_bar`.

`PromptInputBar` is the only widget in this codebase that combines `call_after_refresh` with a synchronous-detach
parent, which is why this race is localized.

## Fix

Minimal, surgical change at the failure site in `src/sase/ace/tui/widgets/prompt_input_bar.py`: catch `NoScreen` in
`_update_height` and silently bail out — there is nothing to size when the bar is no longer in the tree.

```python
from textual.dom import NoScreen

def _update_height(self) -> None:
    if not self.is_mounted:
        return
    try:
        screen_height = self.screen.size.height
    except NoScreen:
        return
    visual_lines = self._get_visual_line_count()
    max_height = screen_height - 2
    completion_rows = self._completion_line_count if self._completion_visible else 0
    new_height = min(max(visual_lines + 2 + completion_rows, 3), max_height)
    self.styles.height = new_height
```

Verified import: `NoScreen` is defined in `textual.dom` and re-exported from `textual.app`. Using
`from textual.dom import NoScreen` matches the path it is raised from.

## Why not a different approach

- **Don't refactor `_detach_prompt_bar` to use Textual's async removal** — the synchronous `_nodes._remove` is
  intentional (see comment at `_prompt_bar_mount.py:196-202`); changing it would reintroduce `DuplicateIds` errors on
  rapid re-mount.
- **Don't track and cancel pending callbacks** — Textual's `call_after_refresh` returns no handle to cancel; building
  one would be invasive for a one-call defensive bail-out.
- **Don't broaden the `is_mounted` check** — `is_mounted` is a Textual-managed state flag and we shouldn't reach into
  private internals to mirror it.

## Steps

1. Edit `src/sase/ace/tui/widgets/prompt_input_bar.py`:
   - Add `from textual.dom import NoScreen` near the other textual imports.
   - Wrap `self.screen.size.height` in `_update_height` with `try/except NoScreen: return`.
2. Add a regression test in `tests/ace/tui/widgets/test_prompt_input_bar_detach.py` (new file, mirrors the style of
   `test_prompt_escape_cancel.py`) that:
   - mounts a `PromptInputBar` inside a minimal `App`;
   - reproduces the synchronous-detach pattern from `_detach_prompt_bar` (`parent._nodes._remove(bar)` +
     `bar.remove()`);
   - directly invokes `bar._update_height()` and asserts it does not raise.
3. Run `just install` then `just check` from this workspace.

## Files touched

- `src/sase/ace/tui/widgets/prompt_input_bar.py` — the fix.
- `tests/ace/tui/widgets/test_prompt_input_bar_detach.py` — new regression test.

## Out of scope

- Auditing every other `call_after_refresh` usage for the same race — none of the other call sites (`file_panel`,
  `_agent_detail_panels`, `tools_panel`, `startup`, `app`) target a widget that is synchronously detached from its
  parent's `_nodes`.
- Reworking the prompt-bar mount/unmount lifecycle.
