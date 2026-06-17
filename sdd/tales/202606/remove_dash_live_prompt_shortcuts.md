---
create_time: 2026-06-17 10:46:04
status: done
prompt: sdd/prompts/202606/remove_dash_live_prompt_shortcuts.md
---
# Remove `---` Live Prompt Shortcuts Plan

## Context

The prompt bar now has explicit controls for both behaviors that used to be available by typing `---` in insert mode:

- `Ctrl+Shift+-` and `,f` open/focus the xprompt properties/frontmatter panel.
- `Ctrl+-` creates a new bottom prompt input pane.

There is still a live text-change path that treats a freshly typed `---` line as UI control syntax:

- at the very beginning of an empty prompt, typing `---` then newline opens the frontmatter panel and removes the typed
  delimiter from the body;
- elsewhere in prompt mode, typing a `---` separator line schedules a live split and rebuilds the bar with a new prompt
  input pane.

Those implicit insert-mode shortcuts are now redundant and surprising. The implementation should make typed `---`
passive text again while preserving the canonical xprompt/multi-prompt syntax used by loaders, editors, history restore,
and launch parsing.

## Goals

1. Remove all live insert-mode side effects caused by typing `---`.
2. Keep explicit panel and pane controls unchanged:
   - `Ctrl+Shift+-` / `ctrl+underscore` and `,f` for the properties panel;
   - `Ctrl+-` for adding a pane.
3. Preserve existing non-live `---` semantics:
   - opening/loading existing xprompt markdown still lifts leading YAML frontmatter and splits body separators into
     panes;
   - whole-stack editor return still parses xprompt markdown;
   - prompt history / initial value paths that already parse multi-prompts keep their current behavior;
   - launch parsing remains the source of truth for a submitted single-pane prompt that contains `---`.
4. Remove user-facing help/docs that advertise `---` as a live shortcut.

## Non-Goals

- Do not remove `---` as the xprompt/multi-prompt separator language.
- Do not change frontmatter parsing, local xprompt completion, or panel editing.
- Do not change configured keymaps in `default_config.yml`; this shortcut is not config-driven.

## Implementation Plan

1. Make prompt text changes passive again.
   - In `PromptInputBarStackRenderingMixin.on_text_area_changed`, keep the existing line-number, completion-context, and
     height updates.
   - Remove the calls that open the frontmatter panel or schedule live split from a text-change event.

2. Remove the frontmatter `---` trigger glue.
   - Delete `_FRONTMATTER_TRIGGER_BODY`, `_should_reserve_for_frontmatter()`, and `_maybe_open_frontmatter_panel()` from
     `_prompt_input_bar_frontmatter.py`.
   - Update that mixin's module docstring so the panel activation paths are existing frontmatter, `,f`, and
     `Ctrl+Shift+-`.

3. Remove live split plumbing.
   - Delete `_maybe_live_split()` and `_live_split_active_pane()` from `_prompt_input_bar_stack_actions.py`.
   - Remove `_live_split_pending` from `PromptInputBar.__init__` and any `TYPE_CHECKING` protocol declarations.
   - Remove `PromptStackState.split_selected_live()` if it has no remaining production callers, along with its dedicated
     pure tests. Keep `split_prompt_text()`, `PromptStackState.from_text()`, and `join()` because they are still the
     canonical non-live parser/joiner paths.

4. Update comments and discoverability.
   - Change the help modal Prompt Input entry from `Ctrl+Shift+- / ,f / ---` to `Ctrl+Shift+- / ,f`.
   - Update `prompt_input_bar.py`, `prompt_text_area.py`, and test module docstrings that still describe leading `---`
     or typed `---` as UI shortcuts.
   - Leave subtitle/footer wording alone unless it currently mentions `---` directly.

5. Update tests to lock the new behavior.
   - Replace the frontmatter-panel trigger test with an inverse test: typing `---` plus newline at the start of an empty
     prompt leaves one prompt input, keeps the panel hidden, and preserves the typed text in the body.
   - Replace the live-split widget test with an inverse test: typing newline then `---` after existing content leaves
     one prompt input, keeps focus in the same pane, and preserves the literal separator text.
   - Keep or adjust the feedback-mode no-op coverage so it still verifies that typed `---` is inert outside prompt mode.
   - Remove or rewrite the pure `split_selected_live()` tests depending on whether the method is removed.
   - Update the help-modal assertion to expect `Ctrl+Shift+- / ,f`.
   - Ensure existing tests still cover canonical non-live separator behavior, especially initial-value splitting,
     all-pane editor reload, prompt-stack launch integration, and launch parser behavior.

## Verification

Run targeted tests first:

```bash
pytest tests/ace/tui/widgets/test_frontmatter_panel.py \
  tests/ace/tui/widgets/test_prompt_stack_keymaps.py \
  tests/ace/tui/widgets/test_prompt_stack.py \
  tests/test_keymaps_display_help.py
```

Then run the repo check after implementation:

```bash
just check
```

Per workspace memory, run `just install` before `just check` if the environment has not already been prepared in this
workspace.

## Risks And Mitigations

- The main risk is accidentally removing canonical `---` multi-prompt behavior instead of only the live insert-mode
  shortcuts. Mitigate by keeping parser/load APIs intact and relying on existing initial-value, editor reload, and
  launch integration tests.
- Another risk is leaving dead delayed-mutation state behind. Removing `_live_split_pending` with the live split
  scheduler keeps the event loop path simpler and avoids stale deferred rebuilds.
- The user-facing terminology is split between "frontmatter" internally and "xprompt properties" in the UI/request. Keep
  internal names unless touching displayed help text, where the existing "Frontmatter panel" label should simply drop
  the `---` shortcut.
