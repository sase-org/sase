---
create_time: 2026-06-17 05:42:28
status: wip
prompt: sdd/prompts/202606/prompt_stack_xprompt_editor.md
---
# Plan: Prompt Stack Xprompt Editor Keymap

## Summary

Add a prompt-input keymap, `Ctrl+Shift+G`, that opens the entire prompt input stack in the user's editor as a valid
xprompt markdown document. Preserve the existing `Ctrl+G` behavior: it edits only the currently active prompt pane, even
when the prompt bar contains multiple panes.

This should be implemented as a sibling path to the current active-pane editor flow, not by changing the semantics of
`PromptInputBar.EditorRequested`.

## Existing Behavior

- `PromptTextArea` binds `ctrl+g` to `action_open_editor()` in `src/sase/ace/tui/widgets/prompt_text_area.py`.
- That action posts `PromptInputBar.EditorRequested(current_text, row, col)`.
- `PromptBarRequestsMixin.on_prompt_input_bar_editor_requested()` handles the request. In a stacked prompt bar it calls
  `stacked_bar.update_active_pane(...)`; in a single-pane bar it preserves the legacy load-or-launch behavior.
- `tests/ace/tui/test_prompt_bar_editor_stack.py` already locks in that `Ctrl+G` edits only the active pane in a
  multi-pane stack.
- `PromptStackState.join()` already knows how to attach prompt-level frontmatter and join non-empty panes with `---`
  separators for launch.
- `PromptFrontmatter.serialize()` already emits the xprompt markdown frontmatter fields from the `sase-4r` epic in
  canonical order: `name`, `description`, `tags`, `input`, `xprompts`, `skill`, `snippet`. It only emits properties that
  were actually set.

## Product Contract

- `Ctrl+G`:
  - Edits only the active prompt pane.
  - Does not open, serialize, replace, submit, or otherwise disturb other panes.
  - Keeps the current single-pane legacy behavior unless the bar is stacked.

- `Ctrl+Shift+G`:
  - Available from prompt input panes in prompt mode.
  - Opens all prompt panes in one markdown file.
  - The file is valid xprompt markdown:
    - optional YAML frontmatter at the top,
    - only set frontmatter properties are included,
    - `input` is canonical, not `inputs`,
    - local `xprompts` are serialized under `xprompts`,
    - prompt panes appear in top-to-bottom launch order,
    - panes are separated by standalone `---` lines outside fenced blocks.
  - Saving the editor result reloads the prompt input stack for continued editing.
  - It does not launch agents. Launch remains `Enter` for the active pane and `Shift+Enter`/`Ctrl+S` for the whole
    stack.
  - Empty editor result is treated as cancel/no-op and keeps the prompt bar mounted.

## Design

### 1. Add an explicit whole-stack editor request

Add a new prompt bar message, probably `StackEditorRequested`, in
`src/sase/ace/tui/widgets/_prompt_input_bar_messages.py`.

Keep it separate from `EditorRequested` so the existing `Ctrl+G` active-pane contract remains obvious in code and tests.
The message does not need to carry pane text directly if the app handler can query the mounted bar; the bar should sync
widget state before posting the request.

### 2. Add the `Ctrl+Shift+G` binding to `PromptTextArea`

Add a binding to `PromptTextArea.BINDINGS`:

```python
("ctrl+shift+g", "open_stack_editor", "Edit all in editor")
```

Implement `action_open_stack_editor()` beside `action_open_editor()`. It should:

- find the containing `PromptInputBar`,
- clear prompt completion / arg hint state like the other editor actions,
- no-op outside prompt mode if feedback and approve-prompt bars should not expose stack editing,
- ask the bar to sync pane state and post the new whole-stack editor message.

Textual 8 accepts `ctrl+shift+g` as a binding string, and the local parser can emit `ctrl+shift+g` from extended
keyboard protocol sequences. Some terminals still collapse `Ctrl+Shift+G` to `Ctrl+G`; verify in ACE after
implementation. If the terminal cannot distinguish it, the implementation should still be correct for environments that
can, and we can decide separately whether to add a configurable fallback.

### 3. Format the stack as xprompt markdown through a pure helper

Add a pure helper near `PromptStackState`, for example `PromptStackState.to_xprompt_markdown()`, instead of open-coding
a join in the event handler.

Recommended formatting:

- Use the stack's current frontmatter string as the top block. When the frontmatter came from the panel, it is already
  canonical via `PromptFrontmatter.serialize()` and includes only set fields from `sase-4r`.
- Do not synthesize unset frontmatter properties.
- Join non-empty pane bodies in stack order with `\n\n---\n\n` for editor readability. This remains valid for the
  existing parser and mirrors checked-in xprompt markdown examples.
- Treat empty drafting panes as absent, matching launch semantics. Empty panes have no representable prompt payload in
  xprompt markdown because the parser intentionally drops empty segments.

This helper is the place to document the empty-pane decision and the fact that editor formatting is a readable xprompt
markdown view, while `join()` remains the launch-canonical compact form used by whole-stack submit.

### 4. Reload the edited markdown without launching

Add a handler in `PromptBarRequestsMixin`, e.g. `on_prompt_input_bar_stack_editor_requested()`.

Flow:

1. Ensure `_prompt_context` exists.
2. Query the mounted `PromptInputBar`.
3. Ask the bar for `to_xprompt_markdown()` after syncing live widget state.
4. Suspend ACE and open the user's editor with that markdown file, reusing `_open_editor_for_agent_prompt()` or a small
   markdown-specific wrapper around it.
5. If the editor returns content, call `bar.load_stack_from_text(edited_content)` so frontmatter and prompt panes are
   rebuilt through the existing parser/stack path.
6. If the editor returns empty/cancel, keep the bar mounted and refocus the active pane.

Important: do not call `_finish_agent_launch()` from this handler. `Ctrl+Shift+G` is edit/reload only.

### 5. Keep frontmatter panel state coherent

Before formatting:

- Sync pane text with `_sync_state_from_widgets()`.
- Rely on `FrontmatterPanel.Changed` events to keep `self._stack.frontmatter` current.
- If needed, add a small bar method that centralizes the sync and formatting so callers do not reach into private stack
  state directly.

After reload:

- Use `load_stack_from_text()` so leading frontmatter auto-shows through the existing frontmatter panel mount path.
- Confirm local `xprompts` from the edited frontmatter still feed prompt completion through the existing
  `local_xprompt_assist_entries()` cache, keyed by the updated frontmatter string.

## Files To Change

- `src/sase/ace/tui/widgets/prompt_text_area.py`
  - Add `ctrl+shift+g` binding and `action_open_stack_editor()`.

- `src/sase/ace/tui/widgets/_prompt_input_bar_messages.py`
  - Add the new whole-stack editor request message.

- `src/sase/ace/tui/widgets/_prompt_input_bar_stack_rendering.py` or `prompt_stack.py`
  - Add a public stack/bar helper that formats all panes as xprompt markdown for the editor.

- `src/sase/ace/tui/widgets/prompt_input_bar.py`
  - Re-export the new message on `PromptInputBar`.

- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_requests.py`
  - Handle the new request and reload the edited markdown into the mounted bar.

- Tests under `tests/ace/tui/...` and `tests/ace/tui/widgets/...`
  - Add focused regression coverage.

No `default_config.yml` change is expected because `PromptTextArea.BINDINGS` owns this widget-local keymap today. If the
implementation moves this binding into the configurable ACE keymap registry, update `default_config.yml`, command/help
metadata, and keymap tests in the same change.

## Test Plan

Add or extend unit/widget tests for:

- `Ctrl+G` still edits only the active pane in a stacked bar.
- `Ctrl+Shift+G` opens editor content containing all non-empty panes in order.
- `Ctrl+Shift+G` includes canonical frontmatter for set properties:
  - scalar fields such as `name` and `description`,
  - `tags`,
  - `input` with type/default/description,
  - local `xprompts`,
  - `skill`,
  - `snippet`.
- Unset frontmatter properties are not emitted.
- Edited markdown reloads into the stack without launching.
- Empty/cancelled editor result keeps the stack mounted and refocuses the prompt.
- Fenced `---` inside a pane remains protected by the existing parser after reload.

After implementation, run:

```bash
just install
just check
```

If the change stays limited and `just check` is too slow during iteration, run the focused tests first, then end with
`just check` as required by the project instructions for repo file changes.

## Risks And Decisions

- `Ctrl+Shift+G` may not be distinguishable from `Ctrl+G` in every terminal. Textual can bind it, and extended keyboard
  protocol can emit it, but the terminal decides what ACE receives. Verify manually in the target terminal.
- The editor markdown export should drop empty panes to match launch semantics. Preserving empty panes would require a
  separate parser/reload path because existing multi-prompt parsing intentionally drops empty segments.
- The whole-stack editor path must never reuse the single-pane legacy "edited text launches unless `%edit` is present"
  behavior. It is always an edit/reload path.
