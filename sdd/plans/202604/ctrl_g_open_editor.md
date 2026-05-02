---
create_time: 2026-04-01 14:21:56
status: done
prompt: sdd/prompts/202604/ctrl_g_open_editor.md
---

# Plan: Add `<ctrl+g>` keymap to XPromptLocationModal to open file in editor

## Problem

The XPrompt location selector modal (`XPromptLocationModal`) — the panel shown during the "add xprompt" workflow (ctrl+o
from the xprompt browser) — lists both **directories** and **config files**. There is currently no way to quickly open a
selected config file in an editor from this modal. Users must leave the modal, find the file, and open it manually.

## Solution

Add a `<ctrl+g>` keybinding that spawns `$EDITOR` on the highlighted location's file. The binding is only active when a
**config file** (not a directory) is selected — selecting a directory and pressing ctrl+g shows a warning notification
instead.

## Scope

Single file change: `src/sase/ace/tui/modals/xprompt_location_modal.py`.

### Changes

1. **New imports** — add `import os`, `import subprocess`, and `from sase.ace.hints import build_editor_args`.

2. **`_LocationFilterInput.BINDINGS`** — add `("ctrl+g", "forward('open_in_editor')", "Open in Editor")` so the key
   press forwards from the focused input widget to the modal action.

3. **`XPromptLocationModal.BINDINGS`** — add `("ctrl+g", "open_in_editor", "Open in Editor")` at the modal level.

4. **`XPromptLocationModal.action_open_in_editor()`** — new method:
   - Get highlighted location via `_get_highlighted_location()`.
   - If `None`, return (nothing highlighted).
   - If `location_type != "config"`, notify with warning and return.
   - Resolve file path from `loc.path`.
   - Suspend TUI, run `$EDITOR` (default `nvim`) via `subprocess.run()`.
   - No reload or git workflow needed — this is a read/edit-in-place action.

5. **Footer hints** — update the hint bar from:
   ```
   "^n/^p: navigate  enter: select  ^d/^u: scroll  Esc: cancel"
   ```
   to:
   ```
   "^n/^p: navigate  enter: select  ^g: open  ^d/^u: scroll  Esc: cancel"
   ```

## Edge cases

- **Directory selected**: show warning notification, no editor spawned.
- **Nothing highlighted**: silent no-op (consistent with other actions in this modal).
- **File doesn't exist yet**: editor opens normally (most editors handle creating new files).

## What this does NOT change

- No changes to the XPromptBrowserModal (the parent modal).
- No new config/keymap entries in `default_config.yml` — this is a modal-internal binding, not an app-level keymap.
- No changes to the actions mixin or helpers.
