---
create_time: 2026-04-22 14:46:33
status: done
prompt: sdd/prompts/202604/fix_ctrl_u_scroll_agents_tab.md
---

# Plan: Fix `ctrl+u` / `ctrl+d` scroll in Agents tab after `v`

## Problem

After pressing `v` in the "Agents" tab of the `sase ace` TUI, the user cannot scroll the agent detail panel using
`<ctrl+u>` (and reportedly `<ctrl+d>`). The expected behavior is identical to scrolling the ChangeSpec detail panel on
the CLs tab while the hint input bar is open.

## Root Cause

Pressing `v` calls `action_view_files` → `_view_agent_files` (`src/sase/ace/tui/actions/hints/_files.py:17-85`), which
mounts a `HintInputBar` inside `#agent-detail-container`. The inner `_HintInput` widget (subclass of textual's `Input`)
takes focus and declares its own readline-style BINDINGS (`src/sase/ace/tui/widgets/hint_input_bar.py:18-24`):

```python
("ctrl+d", "scroll_detail_down", "Scroll Down"),
("ctrl+u", "unix_line_discard", "Clear to start"),
```

- **`ctrl+u` (confirmed bug).** `action_unix_line_discard` (`src/sase/ace/tui/widgets/hint_input_bar.py:38-52`)
  hardcodes `if self._ace_app.current_tab == "changespecs"`. On the agents tab this branch is skipped and control falls
  through to the input-clearing path, so the scroll never happens.
- **`ctrl+d`.** The handler delegates straight to `self._ace_app.action_scroll_detail_down()`, which already has a
  proper `agents` branch (`src/sase/ace/tui/actions/navigation/_basic.py:90-123`). Reading the code, this should already
  work. The user report suggests otherwise, so runtime verification is part of this plan.

## Prior Art

The codebase has a well-established "scroll-up-or-clear" pattern elsewhere — `action_scroll_preview_up_or_clear` — used
in several modals:

- `src/sase/ace/tui/modals/xprompt_browser_modal.py:51-60`
- `src/sase/ace/tui/modals/xprompt_select_modal.py:35-45`
- `src/sase/ace/tui/modals/xprompt_location_modal.py:254-262`
- `src/sase/ace/tui/modals/revive_agent_modal.py:53-62`

Each queries a specific `VerticalScroll`, scrolls up when `scroll_y > 0`, otherwise clears the input from cursor to
start. `_HintInput.action_unix_line_discard` is an older, less general version of the same pattern — it just never got
the `agents` branch.

## Changes

### 1. Extend `ctrl+u` scroll handling to the Agents tab

**File:** `src/sase/ace/tui/widgets/hint_input_bar.py`

Update `action_unix_line_discard` (lines 38-52) so it also resolves a scroll target on the agents tab, reusing the
existing `_get_agent_detail_scroll_id()` helper on the app (`src/sase/ace/tui/actions/navigation/_basic.py:71-88`).
Preserve the dual-use "scroll up, else clear line" semantics so the existing CLs-tab behavior is unchanged.

Logic:

1. Choose a scroll container id based on `self._ace_app.current_tab`:
   - `changespecs` → `#detail-scroll`
   - `agents` → `self._ace_app._get_agent_detail_scroll_id()`
2. If a scroll id was resolved and that container's `scroll_y > 0`, call `self._ace_app.action_scroll_detail_up()` and
   return.
3. Otherwise fall through to the existing line-clear logic.

The HintInputBar is only mounted on the CLs and Agents tabs (see `action_view_files` in
`src/sase/ace/tui/actions/hints/_files.py:17-85`), so no axe branch is needed.

### 2. Runtime verification of `ctrl+d`

Before declaring the fix complete:

1. `just install` (ephemeral workspace may be stale).
2. Launch `sase ace`, switch to the Agents tab, select an agent whose detail panel has enough content to scroll.
3. Press `v` to open the hint input bar, then press `ctrl+d` and `ctrl+u` in turn. Confirm both scroll the active detail
   panel (prompt / thinking / file depending on current panel mode).
4. If `ctrl+d` turns out to be broken, investigate: likely suspects are focus/priority interactions between the textual
   `Input` base class's default bindings and `_HintInput`'s overrides. Extend the plan as needed — do not silently drop
   the failure.

### 3. Validation

- `just check` (runs ruff + mypy + pytest) from the ephemeral workspace.

## Files

- **Modify:** `src/sase/ace/tui/widgets/hint_input_bar.py` (one method body, ~10 lines)
- **Read-only (already examined):** `src/sase/ace/tui/actions/navigation/_basic.py`,
  `src/sase/ace/tui/actions/hints/_files.py`, `src/sase/ace/tui/bindings.py`

## Out of Scope

- Renaming `action_unix_line_discard` to `action_scroll_detail_up_or_clear` to match the modal naming convention — a
  consistency refactor, not a bug fix.
- Adding a mirror "clear line to end" dual-use for `ctrl+d`. The `ctrl+d` binding deliberately dropped the readline
  forward-delete semantics in favor of pure scroll.
- Adding automated tests for `_HintInput` — no existing test infrastructure covers this widget; add manual verification
  in its place.
