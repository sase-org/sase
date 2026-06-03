---
create_time: 2026-06-03 04:48:03
status: done
prompt: sdd/prompts/202606/ctrl_e_xprompt_select_1.md
---
# Plan: Ctrl+E Editor Action in Select XPrompt

## Goal

Add a `Ctrl+E` action to the `Select XPrompt` modal opened from the prompt input widget's `#@` trigger. The action
should open the currently selected xprompt or workflow definition in the user's editor, keep the selector open, and
preserve the normal Enter selection behavior.

## Current Understanding

- `#@` is handled in `PromptTextArea._on_key()` before `@` is inserted. It posts `PromptInputBar.SnippetRequested`.
- `PromptBarRequestsMixin.on_prompt_input_bar_snippet_requested()` responds by pushing `XPromptSelectModal`.
- `XPromptSelectModal` keeps focus on `_XPromptFilterInput`, so modal-level bindings alone are not enough for a reliable
  Ctrl-key action. The filter input should explicitly forward `Ctrl+E` to the modal, as the XPrompt Browser does for its
  own filter input actions.
- `XPromptBrowserActionsMixin.action_edit_xprompt()` already shows the correct editor pattern: resolve a workflow source
  identifier with `resolve_source_to_file_path()`, build command args with `build_editor_args()`, suspend the TUI, and
  run `$EDITOR` or `nvim`.
- This is TUI presentation/glue behavior. It does not need a Rust core change.
- The configurable app keymap registry is for app-level bindings. This quick selector binding is modal-local, so I do
  not plan to add a new `default_config.yml` app keymap.

## Implementation Plan

1. Refactor `XPromptSelectModal` initialization slightly so its prompt catalog can be rebuilt after returning from the
   editor.
   - Store `project` and `extra_prompts` on the modal.
   - Move the current `get_all_prompts()` merge and preview-item construction into a private reload/build helper.
   - Preserve the existing insertion suffix and assist-entry behavior.

2. Add a selected-name helper for the selector.
   - Read the highlighted row from `#xprompt-list`.
   - Validate the highlighted index against `_filtered_names`.
   - Fall back to the first filtered name when there is no valid highlighted row, matching the existing Enter behavior.
   - Return `None` when there are no filtered names.

3. Add a modal action for `Ctrl+E`.
   - Look up the selected workflow by name.
   - Resolve `workflow.source_path` using `xprompt_browser_helpers.resolve_source_to_file_path()`.
   - If there is no selected item, no workflow, or no resolvable source path, notify with a warning or error and do not
     dismiss the modal.
   - Open the resolved path with `build_editor_args(os.environ.get("EDITOR") or "nvim", [file_path])` inside
     `self.app.suspend()`.
   - Catch editor launch `OSError` and notify instead of crashing the modal.
   - Do not offer the XPrompt Browser's git commit prompt from this quick selector. The requested behavior is only to
     open the definition; the browser remains the management surface for add/edit/commit workflows.

4. Wire the keymap and hints.
   - Add `("ctrl+e", "forward('open_selected_in_editor')", "Open Definition")` or equivalent to
     `_XPromptFilterInput.BINDINGS`.
   - Add the matching modal-level binding as a fallback for non-input focus.
   - Update the `Select XPrompt` hint footer to include `^e: open definition`.

5. Refresh the selector after editor return.
   - Rebuild the prompt catalog.
   - Reapply the current filter text.
   - Rebuild the option list and restore the previously selected name when it still exists; otherwise highlight the
     first filtered item.
   - Refresh or clear the preview accordingly.

## Tests

Add focused tests in `tests/ace/tui/modals/test_xprompt_select_modal.py`.

- Unit coverage for source resolution helper behavior through the modal: selected workflow with `source_path` opens the
  resolved file with `$EDITOR`.
- A mounted Textual modal test that presses `Ctrl+E` while the filter input has focus, asserting:
  - the editor command is called with `["test-editor", <path>]`;
  - the call happens while `app.suspend()` is active;
  - the modal remains open and the selection is not dismissed.
- A negative test for an unresolved or missing `source_path`, asserting no editor process is launched and a notification
  is emitted.
- Existing tests for insertion suffixes, assist metadata, filtering, and previews should continue to pass unchanged.

## Verification

After implementation source changes, run:

```bash
just install
just check
```

If a targeted failure needs quicker iteration first, run the focused modal test file before the full `just check`.
