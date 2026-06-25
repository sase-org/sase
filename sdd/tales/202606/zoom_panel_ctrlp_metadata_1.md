---
create_time: 2026-06-25 16:22:52
status: done
prompt: sdd/prompts/202606/zoom_panel_ctrlp_metadata_1.md
---
# Fix Zoom Panel Ctrl-P Return From Metadata-Revealed File Panel

## Problem

In the Agents-tab zoom modal, pressing `Ctrl-N` while the metadata panel is zoomed can reveal and populate the file
panel. Pressing `Ctrl-P` immediately afterward does not return to metadata. It is dispatched as "previous file" because
the modal's active target is now `FILE`; with one file, `AgentFilePanel.prev_file()` returns without changing anything,
so the UI appears stuck.

## Diagnosis

`ZoomPanelModal` currently binds:

- `Ctrl-N` to `action_next_file`
- `Ctrl-P` to `action_prev_file`
- `]` and `[` to panel navigation

Both file actions call `_reveal_file_panel()` when the active target is not `FILE`. `_reveal_file_panel()` changes
`self._target` to `ZoomPanelTarget.FILE` and refreshes the file panel, but it records no origin state. Once the target
is `FILE`, `action_prev_file()` always delegates to `_ZoomFilePanel.prev_file()`. That behavior is correct for normal
file cycling, but it cannot undo the immediately preceding metadata-to-file reveal.

The existing tests cover file cycling, wrapping, and reveal-from-metadata, but they do not cover the specific sequence:
metadata zoom -> `Ctrl-N` reveal first file -> `Ctrl-P` return to metadata.

## Proposed Fix

Keep the existing file-cycling behavior, but make reveal-from-metadata reversible for the immediately opposite keypress.

1. Add small modal-local reveal state to `ZoomPanelModal`, for example:
   - the target that was active before revealing the file panel
   - the key direction that performed the reveal (`next` or `prev`)
   - the file index/path shown immediately after reveal

2. Change `_reveal_file_panel()` to accept the reveal direction from `action_next_file()` / `action_prev_file()`. After
   it shows and refreshes the file panel, record the reveal origin only if the file panel is now active.

3. Before normal file cycling in `action_next_file()` / `action_prev_file()`, check for an immediate opposite-key undo:
   - `Ctrl-N` from metadata reveals the first file.
   - `Ctrl-P` while still on that revealed file returns to metadata.
   - `Ctrl-P` from metadata reveals the first file.
   - `Ctrl-N` while still on that revealed file returns to metadata.

4. Clear the reveal state when:
   - the user cycles files in the same direction as the reveal
   - the user returns to the origin target
   - explicit panel navigation changes targets
   - file/tools visibility changes force the modal back to metadata

This preserves current behavior for normal file-panel zooms and for repeated same-direction file navigation after a
reveal.

## Tests

Add focused regression coverage in `tests/ace/tui/test_agents_zoom_panel_files.py`:

1. A DONE agent with one file:
   - open zoom on metadata
   - press `Ctrl-N`
   - assert file panel is visible and populated
   - press `Ctrl-P`
   - assert metadata is visible and file scroll is hidden

2. A DONE agent with multiple files:
   - open zoom on metadata
   - press `Ctrl-N`
   - press `Ctrl-N` again
   - assert existing same-direction paging still reaches the second file

3. Optional symmetric test:
   - open zoom on metadata
   - press `Ctrl-P`
   - press `Ctrl-N`
   - assert metadata is restored

Run the focused zoom-panel file tests first, then run `just check` after code changes as required by project
instructions.

## Performance Notes

The fix should stay entirely in modal-local UI state and must not add disk I/O, subprocess calls, or blocking work to
key handlers. File refresh behavior should keep using the existing file-panel mechanisms.
