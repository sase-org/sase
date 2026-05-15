---
create_time: 2026-05-15 00:52:08
status: done
prompt: sdd/prompts/202605/ctrl_g_last_vcs_editor.md
---
# Plan: Global Ctrl+G Editor Launch for Last VCS XPrompt

## Goal

Add a global `<ctrl+g>` keymap in `sase ace` that works from any tab and opens the external editor immediately with the
most recently used launchable VCS xprompt prefix, such as `#gh:sase `, pre-populated. Behavior should match the user
pressing `<space>` to repeat the last launch selection and then pressing the prompt input widget's `<ctrl+g>` editor
key, without showing the prompt input widget first.

## Current Shape

- App-level bindings are configured through `src/sase/default_config.yml`, typed in `src/sase/ace/tui/keymaps/types.py`,
  and converted to Textual bindings by `build_app_bindings`.
- The existing `<space>` keymap calls `action_start_agent_from_changespec`, which repeats the last saved `@/<space>`
  selection.
- The existing editor shortcut inside the prompt widget posts an editor request that eventually calls
  `_open_editor_for_agent_prompt` and then `_finish_agent_launch`.
- `_select_and_open_editor_for_home` already combines home prompt-context setup with direct editor launch, including
  `%edit` handling, cancellation history, and finish-launch behavior.
- The most recent VCS xprompt prefixes are tracked in `sase.history.vcs_xprompt_mru`, with
  `load_launchable_vcs_xprompt_mru()` returning reusable prefixes most-recent-first and pruning stale known projects.

## Implementation Steps

1. Add a new app-level action, likely `start_last_vcs_xprompt_in_editor`, to the keymap system:
   - Add it to `AppKeymaps`.
   - Add `_BINDING_META` metadata with a short description and default non-priority binding.
   - Add `ace.keymaps.app.start_last_vcs_xprompt_in_editor: "ctrl+g"` to `src/sase/default_config.yml`.
   - Add the fallback binding to `src/sase/ace/tui/bindings.py` so static defaults stay coherent.

2. Implement `action_start_last_vcs_xprompt_in_editor` in the agent workflow entry points mixin:
   - Load `load_launchable_vcs_xprompt_mru()`.
   - If no entry exists, notify with a warning and do not alter prompt context.
   - Use the first MRU prefix, normalize it to include one trailing space for editor content, and derive a
     display/history key from `extract_project_from_vcs_tag(prefix)` when possible.
   - Call `_select_and_open_editor_for_home(initial_text=..., display_name=..., history_sort_key=...)` to reuse exactly
     the same editor launch, cancellation, `%edit`, and `_finish_agent_launch` behavior as the prompt-widget `Ctrl+G`
     path.

3. Expose the action consistently:
   - Add it to the command palette catalog as an all-tab Agents command.
   - Add it to help-modal sections for Changespecs, Agents, and AXE so users can discover the global key.
   - Leave the prompt-widget `ctrl+g` binding untouched; Textual focus should continue letting the widget-level binding
     handle `ctrl+g` while the prompt bar is active.

4. Add focused tests:
   - Keymap tests covering the new default binding, the increased generated binding count, and the `_BINDING_META` /
     `AppKeymaps` consistency that already exists.
   - Entry-point tests covering:
     - MRU hit opens editor with `#gh:sase ` and launches the edited prompt.
     - MRU miss warns and does not open an editor.
     - Cancelled editor records the pre-populated prefix as cancelled through the reused helper if the existing behavior
       makes that observable in the test harness.
   - Command/help tests only if existing tests require explicit coverage for new visible bindings.

5. Verify:
   - Run targeted tests around keymaps and VCS launch entry points first.
   - Because this repo guidance requires it after code changes, run `just install` if needed and then `just check`
     before final response.

## Risk Notes

- Avoid duplicating editor-launch state handling; `_select_and_open_editor_for_home` should remain the single path for
  direct home-mode editor launch.
- Do not derive the prefix from the saved `@/<space>` selection directly; the request asks for the last VCS xprompt
  workflow, and `vcs_xprompt_mru` is the dedicated persisted source for that.
- Keep this as an app-level keymap so it is active on every tab, while relying on widget focus to preserve the existing
  prompt input `Ctrl+G` behavior.
