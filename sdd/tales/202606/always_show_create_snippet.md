---
create_time: 2026-06-27 11:16:39
status: done
prompt: sdd/prompts/202606/always_show_create_snippet.md
---
# Always Offer Prompt Snippet Creation from `gx`

## Context

The prompt input bar's `gx` action posts `PromptInputBar.SaveAsXpromptRequested` from
`src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py`. That event currently carries the non-empty panes intended
for xprompt saving plus a `single_pane` flag.

The app-level handler in `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt.py` builds the combined
xprompt body from those panes and gates the save-target modal's `Create a new snippet...` row with:

```python
allow_create_snippet = event.single_pane and non_empty_count == 1
```

That is why the snippet row disappears whenever the prompt stack has multiple visible prompt panes, even when the
current pane has a perfectly valid body that could be saved as a snippet.

## Goal

Always show `Create a new snippet...` on the `gx` save-target panel. When the prompt stack has multiple panes, choosing
that row must save only the currently active pane's text as the snippet template. Existing xprompt creation and
overwrite behavior should continue to use the full non-empty pane list joined with `\n---\n`.

## Design

1. Extend `PromptInputBar.SaveAsXpromptRequested` with a separate snippet-source payload, for example
   `snippet_body: str | None = None`.
   - Keep the existing `panes` payload as the xprompt-save source.
   - Keep `single_pane` only as compatibility/context unless tests or callers no longer need it.
   - Update the message docstring so it clearly distinguishes the xprompt body source from the snippet body source.

2. Capture the active pane body in `request_save_as_xprompt()`.
   - Call `_sync_state_from_widgets()` as it already does.
   - Store `snippet_body = self._stack.selected_item.text.strip()` before or alongside the existing filtered `panes`
     construction.
   - Do not change the existing `panes` filtering or frontmatter-only fallback; those semantics belong to xprompt
     saving, not snippet saving.
   - Post `SaveAsXpromptRequested(panes, single_pane=single_pane, snippet_body=snippet_body)`.

3. Change the app save handler to make the modal option unconditional for the opened panel.
   - Pass `allow_create_snippet=True` to `XPromptSaveTargetModal` whenever the handler is opening the modal.
   - For direct/backward-compatible events without `snippet_body`, fall back to the old single-pane body only when that
     is unambiguous.
   - When the user selects `create_snippet`, call `_create_snippet_flow()` with the captured active-pane snippet body,
     not the combined xprompt body.
   - If the captured snippet body is blank, show a warning such as
     `Current prompt pane is empty - nothing to save as a snippet` and do not enter the config/name/write flow. This
     preserves "always show the option" while preventing empty snippet writes in edge cases like frontmatter-only drafts
     or an empty active pane beside non-empty inactive panes.

4. Consider the modal preview copy for the snippet row.
   - The current preview summary describes the whole xprompt draft (`Draft: N panes, frontmatter: yes/no`).
   - If that reads as misleading in multi-pane cases, adjust the snippet preview to indicate that the snippet source is
     the current pane while leaving the create/overwrite xprompt previews unchanged.
   - Keep this scoped to the modal's existing preview text; no layout or keymap changes are needed.

## Tests

1. Widget capture tests in `tests/ace/tui/widgets/test_prompt_stash_capture.py`.
   - Assert single-pane `gx` events carry `snippet_body == "solo draft"`.
   - Add a multi-pane case where the active pane is not the only non-empty pane and assert:
     - `event.panes` still contains all non-empty panes in launch order.
     - `event.single_pane is False`.
     - `event.snippet_body` equals only the active pane text.
   - Add or adjust an empty-active-pane case if needed to prove the event can distinguish "xprompt body exists" from
     "snippet body is blank".

2. Handler tests in `tests/ace/tui/actions/test_prompt_save_xprompt.py`.
   - Replace the old "multi-pane request disables snippet option" expectation with a test that multi-pane requests
     enable the modal snippet option.
   - Add a create-snippet flow test where the event has multiple pane bodies but `snippet_body` is one pane; assert the
     written YAML snippet contains only that active-pane body and not the `\n---\n`-joined xprompt body.
   - Add a blank `snippet_body` selection test that asserts a warning is emitted and no config/name modal is pushed.

3. Modal tests in `tests/ace/tui/modals/test_xprompt_save_target_modal.py`.
   - Keep the existing hidden/shown tests unless the modal API is simplified. The handler can always pass
     `allow_create_snippet=True` without requiring the modal itself to always show the row in isolation.
   - If the snippet preview text changes, add/update a focused assertion for the multi-pane/current-pane summary.

## Verification

After implementation, run targeted tests first:

```bash
just install
pytest tests/ace/tui/widgets/test_prompt_stash_capture.py \
  tests/ace/tui/actions/test_prompt_save_xprompt.py \
  tests/ace/tui/modals/test_xprompt_save_target_modal.py
```

Because this changes files in the repo, finish with:

```bash
just check
```

No changes are expected in linked repositories or in the Rust core backend; this is a TUI event-payload and save-flow
behavior change.
