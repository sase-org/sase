---
create_time: 2026-06-27 08:09:59
status: done
prompt: sdd/prompts/202606/create_prompt_snippet_option.md
---
# Plan: Add Prompt Save-As Snippet Option

## Goal

Add a `Create a new snippet...` choice to the save menu opened by the prompt input `gx` / `Ctrl+G x` keymaps. The option
should turn the current single prompt draft into an ACE snippet stored under `ace.snippets` in a selected SASE YAML
config file, while preserving comments and unrelated formatting in that file.

## Current Shape

- `gx` / `Ctrl+G x` dispatches through `PromptInputBar.request_save_as_xprompt()`.
- That posts `PromptInputBar.SaveAsXpromptRequested`, handled by
  `PromptBarSaveXpromptMixin.on_prompt_input_bar_save_as_xprompt_requested()`.
- The menu is `XPromptSaveTargetModal`, which currently supports:
  - `Create new xprompt...`
  - overwrite an existing simple xprompt target
- Existing config-backed xprompt saves use `sase.xprompt.config_yaml`, a minimal-edit string splicer for top-level
  `xprompts:`.
- ACE user snippets are loaded from merged config at `ace.snippets`, then cached in the app as `_user_snippets` /
  `_snippets_cache`.

## UX And Scope

1. In the `gx` / `Ctrl+G x` save-target menu, add a pinned `Create a new snippet...` option near
   `Create new xprompt...`.
2. Only show this option when the prompt bar has exactly one prompt input pane and that pane has non-blank body text. Do
   not show it for multi-pane prompt stacks, even if only one pane currently has text.
3. Selecting the option opens a config-file selector containing valid writable SASE YAML config files only, not xprompt
   directories.
4. After a config file is selected, prompt for a snippet trigger name.
5. Validate snippet names with the existing ACE trigger rule `is_valid_snippet_trigger()` (`[A-Za-z0-9_]+`).
6. If the selected file already has `ace.snippets.<name>`, overwrite that entry without a second confirmation. The name
   prompt should still warn that the selected file already defines it.
7. On success, show a useful toast like: `Created snippet 'foo' in ~/.config/sase/sase.yml`
8. On write or validation failure, show an error toast and leave the prompt bar mounted and unchanged.

## Implementation

1. Extend the save-target result model.
   - Add a new target kind such as `create_snippet` to `XPromptSaveTarget`.
   - Add an `allow_create_snippet` constructor flag to `XPromptSaveTargetModal`.
   - Render the new option only when that flag is true.
   - Update preview text and selection logic for the new option.

2. Carry the single-pane gate from the prompt bar.
   - Extend `SaveAsXpromptRequested` to include the total prompt-pane count, or a boolean such as `allow_snippet_save`.
   - In `request_save_as_xprompt()`, compute it from `len(self._stack) == 1` before filtering empty panes.
   - In the app handler, pass `allow_create_snippet=True` only when there is one pane and exactly one non-empty captured
     body.

3. Add a config-file selector for snippets.
   - Prefer a small config-only modal/helper instead of reusing the xprompt location modal unfiltered.
   - Candidate rows should include user `sase.yml`, existing user overlays, and an existing local `./sase.yml` when
     relevant, applying the same chezmoi source-path remapping used elsewhere.
   - Disable or omit non-YAML paths, invalid YAML documents, read-only files, and paths whose parent cannot be created.
   - Keep the modal loading/discovery callable from a worker thread so the TUI event loop is not blocked.

4. Add a snippet-name modal.
   - Create a small modal similar to `XPromptNameModal`, but with snippet-specific validation through
     `is_valid_snippet_trigger()`.
   - Load existing snippet names from only the selected YAML file, not from the merged config, so overwrite behavior
     matches the selected file.
   - Show a warning when the selected file already contains the name, but allow submit.

5. Add a minimal-edit YAML writer for `ace.snippets`.
   - Implement a pure helper, for example `insert_snippet_into_config(config_path, name, template)`.
   - Pattern it after `sase.xprompt.config_yaml`: edit only the affected section where possible, preserve comments/blank
     lines around unrelated keys, replace only the matching snippet block on overwrite, and append/create `ace:` and
     `ace.snippets:` when missing.
   - Generate block-scalar snippet values so multiline prompt text round-trips: `ace: -> snippets: -> name: |`.
   - Treat empty/missing files as valid and create the necessary parent mapping.

6. Wire the async save flow.
   - Add a `_create_snippet_flow(body)` branch in `PromptBarSaveXpromptMixin` after the save menu returns the new kind.
   - Load config locations and existing names with `asyncio.to_thread()`.
   - Write the YAML file with `asyncio.to_thread()` or the existing tracked-task pattern; keep all disk I/O off the
     Textual event loop.
   - After a successful write, refresh the app’s effective snippet state: invalidate config/snippet caches, reload
     merged `ace.snippets`, set `_user_snippets`, and clear `_snippets_cache`.
   - Reuse the existing git commit offer path after the write, with snippet wording in the suggested commit subject if
     adding a new helper is warranted.

## Tests

1. YAML helper unit tests:
   - creates `ace.snippets` in an empty file;
   - inserts under existing `ace:` without disturbing sibling keys/comments;
   - inserts into existing `ace.snippets`;
   - overwrites only the matching snippet block;
   - preserves unrelated comments, blank lines, ordering, and formatting.

2. Modal tests:
   - `XPromptSaveTargetModal` shows `Create a new snippet...` only when allowed;
   - selecting it returns the new target kind;
   - snippet-name modal rejects invalid triggers and allows existing names with a warning.

3. Prompt bar tests:
   - single-pane `gx` event enables snippet creation;
   - multi-pane stacks do not enable snippet creation, including the case where only one pane has non-empty text.

4. App flow tests:
   - selecting snippet creation opens the config selector, then the name modal;
   - successful write updates the selected YAML file and shows the success toast;
   - same-file duplicate name overwrites;
   - app snippet cache is refreshed so `get_snippets()` sees the new template.

5. Verification:
   - run `just install` first in the workspace;
   - run targeted tests while iterating;
   - run `just check` before finishing implementation changes.
