---
create_time: 2026-06-17 07:10:57
status: done
prompt: sdd/prompts/202606/prompt_input_all_editor.md
---
# Plan: Prompt Input All-Panes Editor Keymap

## Context

The prompt input surface is now a stack of `PromptTextArea` panes backed by `PromptStackState`. `Ctrl+G` is currently a
widget-local binding on `PromptTextArea`: it posts `PromptInputBar.EditorRequested` with the focused pane's text and
cursor position. The app handler then opens only that text in the user's editor. In a stacked prompt bar, the editor
result is written back to the active pane with `update_active_pane()` and the rest of the stack is left alone. This
already matches the desired "current prompt input widget only" intent, but it needs a regression test because the app
also has a global `ctrl+g` binding for "edit last VCS xprompt".

The `sase-4r` epic established the prompt frontmatter field set and structured round-trip: `name`, `description`,
`tags`, `input`, `xprompts`, `skill`, and `snippet`. The shared prompt stack stores that frontmatter as canonical
`---`-delimited YAML, and `PromptFrontmatter.serialize()` emits only fields that are actually set, in xprompt-compatible
order. Whole-stack submit already joins non-empty panes with `---` segment separators and reattaches the shared
frontmatter, so the desired all-pane editor content is very close to the existing launch representation.

TUI performance guidance requires avoiding new synchronous work in hot keypress paths. The existing editor flow is a
user-initiated suspended-TUI path; the new all-pane editor should follow that shape and keep key handling itself limited
to clearing transient completion state and posting a message.

## Goals

- Preserve `Ctrl+G` as an active-pane-only editor keymap.
- Add `Ctrl+Shift+G` on the prompt input widget to open the whole prompt stack in `$EDITOR`.
- Format the all-pane editor buffer as xprompt markdown:
  - leading frontmatter only when prompt frontmatter properties are set;
  - canonical frontmatter properties from the existing `PromptFrontmatter` model, including `input` and `xprompts`;
  - prompt panes in launch order, separated by markdown `---` segment lines;
  - no empty `---\n---` frontmatter block when no properties are set.
- On editor return, reload the edited xprompt markdown back into the prompt bar as a stack, lifting leading frontmatter
  back into the structured panel state.
- Keep the app-level `ctrl+g` "last VCS xprompt" action available outside the prompt input, but ensure prompt-input
  focus shadows it.

## Non-Goals

- No new xprompt frontmatter fields.
- No new CLI subcommands or options.
- No changes to launch-time input substitution, local xprompt parsing, or the `sase-core` frontmatter schema API.
- No attempt to preserve arbitrary hand-authored YAML comments/formatting beyond the existing canonical frontmatter
  model.

## Design

1. **Pin current `Ctrl+G` behavior.**
   - Keep `PromptTextArea.BINDINGS` entry `("ctrl+g", "open_editor", ...)`.
   - Add tests that a focused pane's `Ctrl+G` posts only that pane's text and does not call the app-level
     `action_start_last_vcs_xprompt_in_editor`.
   - Keep the current multi-pane handler behavior: editor result updates only the active pane and never expands to the
     whole stack.

2. **Add a distinct all-stack editor request.**
   - Add a `PromptInputBar.AllEditorRequested` message.
   - Add `("ctrl+shift+g", "open_all_editor", "Edit all in editor")` to `PromptTextArea.BINDINGS`.
   - Implement `PromptTextArea.action_open_all_editor()` to clear transient completion/arg-hint state, find the parent
     bar, and post the new message. The action should not do disk I/O or parse YAML on the keypress path.

3. **Serialize the editor buffer through prompt-stack/xprompt contracts.**
   - Add a small `PromptInputBar`/`PromptStackState` helper for "xprompt markdown for editor" that first syncs live
     widgets into `PromptStackState`, then returns the stack joined with frontmatter.
   - Reuse the stack's existing `frontmatter` string. Because panel edits write back through
     `PromptFrontmatter.serialize()`, set properties are already emitted with the correct xprompt frontmatter names and
     structure.
   - For single-pane prompts that already contain inline leading frontmatter, preserve the text as authored when opening
     the all editor. When the edited file is later reloaded through the all-stack path, leading frontmatter will be
     lifted into the shared stack frontmatter.

4. **Reload all-stack editor results without launching.**
   - Add a bar method such as `load_stack_from_xprompt_markdown()` that uses `PromptStackState.from_text()` directly
     instead of the existing `load_stack_from_text()` heuristic. This is important because the normal history-load path
     intentionally keeps a single prompt with frontmatter as a verbatim pane, while the all-editor path should treat the
     file as xprompt markdown and lift frontmatter even for one body pane.
   - In `PromptBarRequestsMixin`, handle `AllEditorRequested` by opening the joined xprompt markdown via the existing
     `_open_editor_for_agent_prompt()`.
   - On non-empty editor return, strip `%edit` if present for consistency with other editor-return paths, then reload
     the whole prompt bar from the edited xprompt markdown. Do not launch from this all-stack editor path.
   - On empty editor return, keep the prompt bar mounted and refocus the active pane, matching the stacked `Ctrl+G`
     no-op behavior.

5. **Update discoverability.**
   - Update the prompt input placeholder/subtitle text so users can discover both editor scopes without adding noisy
     app-level footer entries.
   - Do not add a configurable `default_config.yml` app binding unless the existing prompt text-area bindings are made
     configurable as a broader change. The current `Ctrl+G` prompt editor binding is widget-local, so the new sibling
     binding should stay widget-local too.
   - Check whether the `?` help popup has a prompt-input section; if it does, update it. If it does not, keep the
     discoverability change localized to the prompt widget text and avoid inventing a new help-modal section for this
     narrow change.

## Test Plan

- Add/extend pure widget tests for:
  - `Ctrl+G` active-pane-only behavior;
  - new all-editor message/action using the full joined stack;
  - all-editor serialization with canonical frontmatter containing `description`, `tags`, `input`, `xprompts`, `skill`,
    and `snippet`;
  - empty frontmatter produces no empty delimiter block;
  - reloading edited xprompt markdown lifts frontmatter and splits panes.
- Extend `tests/ace/tui/test_prompt_bar_editor_stack.py` with app-handler tests:
  - all-editor opens the whole stack text, not the active pane;
  - non-empty return reloads the bar and does not call `_finish_agent_launch`;
  - empty return keeps the bar mounted and refocuses;
  - `Ctrl+G` single-pane/multi-pane behavior remains unchanged.
- Add a regression test for the global `ctrl+g` conflict while prompt input is focused. If Textual's test driver cannot
  synthesize `ctrl+shift+g` reliably, test the binding metadata plus `action_open_all_editor()` directly.
- Run:
  - `just install`
  - focused pytest for prompt stack/editor/frontmatter tests
  - `just check`

## Risks

- `Ctrl+Shift+G` may not be distinguishable from `Ctrl+G` in some terminals. Textual already accepts `ctrl+shift+d`
  elsewhere, so define the binding and cover the action path; if local pilot delivery is flaky, keep tests at the
  action/binding level.
- The normal `load_stack_from_text()` path intentionally preserves single prompts with frontmatter verbatim. The
  all-editor reload must use a separate xprompt-markdown path so this new behavior does not regress history loads.
- `---` serves as both frontmatter delimiter and segment separator. Reusing `PromptStackState.from_text()` and the
  canonical multi-prompt parser avoids a second parser and keeps fenced-code protection intact.
