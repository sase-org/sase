---
create_time: 2026-06-23 09:01:43
status: done
prompt: sdd/prompts/202606/zoom_file_reverse_cycle.md
---
# Plan: Fix ACE zoom modal previous-file cycling

## Context

Recent zoom-panel changes fixed two related issues:

- seeded file-panel content now paints in the zoom modal instead of staying blank until refresh;
- `<ctrl+n>` / `<ctrl+p>` can reveal the file panel when zoom opens on metadata or tools.

The remaining reported behavior is narrower: inside the zoom modal, `<ctrl+n>` advances through files, but `<ctrl+p>`
does not reliably move back to the previous file. The requested behavior is:

- `<ctrl+n>` moves to the next file;
- `<ctrl+p>` moves to the previous file;
- `<ctrl+n>` wraps from the last file to the first;
- `<ctrl+p>` wraps from the first file to the last.

This is presentation-layer Textual work only. It does not cross the Rust core backend boundary.

## Findings So Far

`AgentFilePanel.next_file()` and `AgentFilePanel.prev_file()` already use modulo arithmetic, so the core index operation
is designed to wrap in both directions.

The zoom modal delegates to that file panel:

- `ZoomPanelModal.action_next_file()` calls `_ZoomFilePanel.next_file()`;
- `ZoomPanelModal.action_prev_file()` calls `_ZoomFilePanel.prev_file()`;
- if the active zoom target is not `FILE`, both actions currently reveal the file panel and return.

Existing tests cover:

- seeded file list loading;
- `<ctrl+n>` advancing to the next seeded file;
- `<ctrl+n>` revealing the file panel from metadata;
- `<ctrl+p>` revealing the file panel from metadata for a single-file agent;
- reveal-then-page behavior for `<ctrl+n>`.

Existing tests do not cover:

- `<ctrl+p>` moving among multiple files in the zoom modal;
- `<ctrl+p>` wrapping from the first file to the last;
- `<ctrl+n>` wrapping from the last file to the first;
- reveal-then-reverse-page behavior after the file panel is initially collapsed.

Plain `pytest` is not usable in this workspace yet because the system Python lacks project TUI dependencies. Validation
should use the repo path from `memory/build_and_run.md`: `just install` if needed, then targeted `just test ...`, and
`just check` after source changes.

## Implementation Strategy

1. Reproduce with targeted tests first.

   Add focused tests in `tests/ace/tui/test_agents_zoom_panel.py` using the existing Textual pilot harness and real
   temporary files. The tests should mount `ZoomPanelModal`, wait for the expected file body to render, press keys, and
   assert both `current_file_index` and rendered content.

2. Cover reverse paging and both wrap edges.

   Add tests for these scenarios:
   - start on the second file, press `<ctrl+p>`, expect the first file;
   - start on the first file, press `<ctrl+p>`, expect the last file;
   - start on the last file, press `<ctrl+n>`, expect the first file;
   - open collapsed on metadata, reveal the file panel, then press `<ctrl+p>` and expect reverse paging/wrap behavior.

3. Keep file index behavior centralized in `AgentFilePanel` if possible.

   Since `AgentFilePanel` already implements wrapping, avoid duplicating index math in the modal unless the failing test
   proves the modal is bypassing or corrupting that state.

4. Make zoom-modal file-key dispatch unambiguous.

   If the failing test shows `action_prev_file()` is not being invoked or is being shadowed by the focused
   `VerticalScroll`, update the zoom modal key handling rather than the file panel. The likely minimal fix is to make
   the modal-local `<ctrl+n>` / `<ctrl+p>` bindings priority bindings, or add a small modal-level key dispatch fallback
   that stops the event after routing to `action_next_file()` / `action_prev_file()`.

5. Hydrate before cycling only if needed.

   If the failing test shows `action_prev_file()` is invoked but the zoom file panel has an empty or stale file list,
   add a small helper in `ZoomPanelModal` that ensures the file panel has loaded the current agent's file list before
   applying the requested cycle step. Preserve the current reveal semantics from the previous plan: the first off-target
   file-key press reveals the file panel and does not skip a file.

6. Avoid unrelated keymap/config changes.

   The modal already declares `<ctrl+n>` / `<ctrl+p>` bindings and the app default config already has the base
   `next_agent_file` / `prev_agent_file` bindings. No `src/sase/default_config.yml`, footer, or help-modal update is
   expected unless the investigation proves the user-facing keymap contract changed.

## Validation

Run after implementation:

- `just install` if the workspace venv is absent or stale;
- targeted tests for `tests/ace/tui/test_agents_zoom_panel.py`;
- targeted tests for `tests/ace/tui/test_file_panel_selection_preserved.py` if `AgentFilePanel` changes;
- `just check` before final response, per project instructions.

Manual smoke after tests:

- in `sase ace`, select an agent with at least two files;
- open the zoom panel on the file target;
- verify `<ctrl+n>` advances and wraps last -> first;
- verify `<ctrl+p>` retreats and wraps first -> last;
- open zoom while the file panel is collapsed, reveal files with a file key, then verify both directions still cycle.

## Risks

- A Textual focus-level binding conflict could pass direct method tests but fail in the real pilot/app path, so coverage
  must use `pilot.press("ctrl+p")` against a mounted modal rather than only calling `action_prev_file()` directly.
- Active agents can have live diff content without a stable `all_files` list. The fix should not make active-agent live
  diff refresh more expensive or block the event loop.
- Periodic zoom refresh must not reset the user's selected file after cycling. Existing selection-preservation tests
  should remain green.
