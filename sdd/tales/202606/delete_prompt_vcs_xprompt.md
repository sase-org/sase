---
create_time: 2026-06-21 09:14:29
status: done
prompt: sdd/prompts/202606/delete_prompt_vcs_xprompt.md
---
# Delete Prompt VCS XPrompt Keymap Plan

## Goal

Change the prompt-local `Ctrl+N` behavior so, when the prompt contains a VCS xprompt workflow ref such as `#git:foo`,
the first `Ctrl+N` press removes that ref from the prompt. If the prompt has no VCS workflow ref, `Ctrl+N` should be a
prompt-local no-op. The prompt-local `Ctrl+N` / `Ctrl+P` keymaps should no longer cycle through VCS xprompt MRU entries.

This applies to the prompt text area only. Existing file-completion navigation keeps precedence while the file
completion menu is active, and existing app-level `Ctrl+N` / `Ctrl+P` file navigation outside the prompt is not part of
this change.

## Current Behavior

`PromptTextArea._on_key()` currently gives active file completion first claim on `Ctrl+N` / `Ctrl+P`. When file
completion is not active, it calls `_handle_vcs_mru_cycle_key()` from `src/sase/ace/tui/widgets/_vcs_mru_cycling.py`.

That mixin loads `load_launchable_vcs_xprompt_mru()` synchronously on the keypress path, computes a next MRU index, and
inserts, replaces, or prepends a VCS workflow prefix. The pure-function and widget tests in
`tests/ace/tui/widgets/test_vcs_mru_cycling_logic.py` and `tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py`
intentionally pin the cycling behavior, so they need to be rewritten around deletion.

The MRU history module should remain. It is still used by launch recording and by
`action_start_last_vcs_xprompt_in_editor()`, which opens the most recently used launchable VCS xprompt in the editor.

## Design

Replace prompt-local VCS MRU cycling with a deterministic text edit that deletes the first real VCS workflow tag in the
prompt:

- Use the existing `find_vcs_workflow_tag_span()` parser so behavior stays aligned with launch parsing and continues to
  skip fenced code blocks.
- Do not load MRU history or touch disk from the prompt key handler.
- Consume `Ctrl+N` in insert mode after file-completion handling whether or not a tag is found, so "does nothing" does
  not bubble to app-level file navigation while the prompt owns focus.
- Consume `Ctrl+P` in the same prompt-local position as a no-op, preserving file-completion precedence but retiring
  prompt cycling for both former cycle keys.
- Clear soft completion, file completion, xprompt argument hints, and prompt-completion context only when a deletion is
  actually applied. A no-op keypress should not churn transient UI state.

Deletion should clean up local separator whitespace rather than leaving awkward prompt text:

- `#git:foo fix` becomes `fix`.
- `%n:a #git:foo fix` becomes `%n:a fix`.
- `fix #git:foo` becomes `fix`.
- `fix #git:foo more` becomes `fix more`.
- A tag followed by a newline should not leave a blank first line when the tag was alone before body text.
- Tags inside fenced blocks remain untouched and therefore make `Ctrl+N` a no-op.

Cursor behavior should be predictable:

- Cursor before the deleted range stays where it was.
- Cursor inside the deleted range snaps to the deletion start.
- Cursor after the deleted range shifts by the length removed.
- The final cursor offset is clamped to the new text length.

## Implementation Steps

1. Replace the cycling helper surface.
   - Rename or replace `_vcs_mru_cycling.py` with a prompt VCS-tag edit helper, for example `_vcs_xprompt_delete.py`.
   - Introduce a pure function like `_delete_vcs_xprompt_text(text, cursor_offset)` returning an edit object or `None`.
   - Base tag detection on `find_vcs_workflow_tag_span()`.
   - Implement separator cleanup and cursor offset calculation in the pure function.

2. Update `PromptTextArea`.
   - Import the new mixin/helper instead of `VcsMruCyclingMixin`.
   - Remove `_vcs_mru_index` state and reset plumbing if no longer referenced.
   - In `_prompt_text_area_key_handling.py`, after active file-completion handling:
     - route `Ctrl+N` to the delete handler and always consume it;
     - route `Ctrl+P` to a prompt-local no-op and always consume it;
     - keep feedback mode from mutating the prompt, matching the current "no prompt-local VCS edit in feedback" guard.

3. Leave MRU persistence and launch history intact.
   - Do not change `sase.history.vcs_xprompt_mru`.
   - Do not change `record_resolved_vcs_xprompt_usage()` or launch MRU recording.
   - Keep the previous default-filtering behavior because `Ctrl+G` editor launch still reads launchable MRU entries.

4. Rewrite prompt widget tests.
   - Replace cycling assertions with deletion assertions in the widget-level prompt tests.
   - Cover deleting an existing tag, no-op with no tag, no-op when only a fenced-block tag exists, feedback-mode no-op,
     and active file-completion precedence for `Ctrl+N` / `Ctrl+P`.
   - Add an assertion that `Ctrl+P` no longer loads MRU or mutates the prompt.

5. Rewrite pure-function tests.
   - Replace `_cycle_vcs_mru_text` tests with deletion edit tests for start, middle, end, directive/frontmatter,
     newline, fenced-block, and cursor-position cases.
   - Remove assertions about MRU index, cycling order, and underscore-normalized MRU lookup because prompt cycling no
     longer exists.

6. Update stale comments/test names.
   - Rename tests and module docstrings that currently describe prompt MRU cycling.
   - Keep launch-path tests that validate submitted-text VCS resolution, but adjust comments that specifically say
     "cycled-to ref" if they become misleading.

7. Verify.
   - `just install`
   - `pytest tests/ace/tui/widgets/test_vcs_mru_cycling_logic.py tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py tests/ace/tui/widgets/test_prompt_history_trigger.py`
   - `pytest tests/ace/tui/test_agent_launch_vcs.py tests/ace/tui/test_entry_points_vcs_prefix_errors.py tests/test_vcs_xprompt_mru.py`
   - `just check`

## Risks and Checks

- The key handler must not reintroduce synchronous MRU loading on the Textual event loop; the new prompt-local behavior
  should be pure text manipulation only.
- File-completion navigation must retain `Ctrl+N` / `Ctrl+P` precedence while completion is active.
- Prompt-local no-op handling should consume `Ctrl+N` / `Ctrl+P` so a no-op does not unexpectedly navigate files in the
  underlying app while the user is typing.
- Parser reuse is important: deleting should match the same VCS workflow refs that launch parsing sees, not ad hoc
  string prefixes.
- No Rust core boundary work is expected; this remains Python TUI prompt-editing behavior.
