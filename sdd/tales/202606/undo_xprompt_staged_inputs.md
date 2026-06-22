---
create_time: 2026-06-22 08:28:26
status: done
prompt: sdd/prompts/202606/undo_xprompt_staged_inputs.md
---
# Plan: Make XPrompt-Staged Inputs Follow Prompt Undo

## Problem

`#@` + `Ctrl+I` now inline-expands input-bearing markdown xprompts by doing two mutations:

1. replacing the trigger `#` in the originating `PromptTextArea` with the rendered body, and
2. merging the xprompt's `input:` declarations into the prompt-level frontmatter shown by the xprompt property panel.

The first mutation is already a single TextArea undo batch, so prompt NORMAL-mode `u` restores the original body text.
The second mutation is prompt-stack frontmatter state, so it currently survives that undo. This leaves stale input
properties in the property panel, and when those were the only prompt properties, the panel remains visible even though
the body expansion has been undone.

Desired behavior: undoing the inline expansion should also remove the input properties that expansion auto-staged, and
the property panel should hide when no properties remain. User-authored properties, pre-existing input declarations, and
unrelated panel edits must not be clobbered.

## Design Goals

- Keep the body splice as the source of truth for when the expansion itself is undone or redone.
- Couple only auto-staged xprompt inputs to that body undo; do not make all frontmatter part of TextArea undo.
- Preserve existing prompt-level declarations on collisions, just as the current merge behavior does.
- Preserve unrelated frontmatter fields (`description`, `xprompts`, `tags`, etc.) when an expansion is undone.
- Keep the fix fully in-memory on the Textual event path. No disk I/O, subprocesses, or heavyweight refreshes in key
  handlers.
- Account for prompt stacks: frontmatter is shared across panes, while TextArea undo history is per pane.

## Proposed Approach

Introduce a small prompt-level sidecar transaction for `Ctrl+I` inline expansions that stage inputs.

Each transaction records:

- the originating `PromptTextArea` / pane id,
- the text before and after the expansion splice,
- the input declarations returned by `expand_inline_xprompt`,
- which declarations were actually inserted into prompt frontmatter, and
- whether the body edit is currently active or undone.

The transaction does not replace Textual's undo history. It observes normal-mode undo/redo by comparing the TextArea
text immediately before and after `undo()` / `redo()`:

- On `u`, if the text changed from a transaction's `after_text` back to its `before_text`, mark that transaction undone
  and unstage its expansion-owned inputs.
- On `Ctrl+R`, if the text changed from `before_text` back to `after_text`, mark the transaction active again and
  restage its expansion-owned inputs.

This avoids reaching into Textual's private history stacks while still tying the frontmatter mutation to the same
observable edit boundary the user sees.

## Frontmatter Ownership Rules

`merge_frontmatter_inputs` should return the declarations it actually added. A declaration skipped because it already
existed is not owned by the current expansion and must not be removed by undo.

When undoing an expansion, remove only auto-owned input names. Do this through `PromptFrontmatter.parse` and model
mutation, not YAML string surgery. Then write back with `PromptStackState.set_frontmatter_model()`:

- If other fields or inputs remain, keep the panel visible and synced.
- If the model becomes empty, serialization clears `self._stack.frontmatter`, and
  `refresh_frontmatter_panel_from_stack()` hides the property panel without moving focus.
- If frontmatter is currently invalid or mid-edit, do not blindly rewrite it; leave it unchanged rather than clobbering
  user text.

For multi-pane/shared-input cases, maintain prompt-bar ownership/refcount state for auto-staged input names:

- Every active expansion transaction records the input names its body depends on.
- If expansion A auto-added `topic` and expansion B later uses the same `topic`, undoing A should not remove `topic`
  while B's body expansion is still active.
- Once the last active expansion depending on an auto-owned input is undone, remove that input unless a user-authored
  declaration has replaced it.

This keeps the common single-expansion behavior simple while avoiding broken placeholders in other panes.

## Implementation Steps

1. Add an internal dataclass or small model in the prompt input bar/frontmatter area for inline-expansion input
   transactions.
2. Change `merge_frontmatter_inputs(inputs)` to report which inputs were actually added, while keeping its existing
   collision behavior and panel refresh.
3. Update the `Ctrl+I` callback path in `_prompt_bar_requests.py` so a successful body splice plus non-empty staged
   input merge registers a transaction on the origin bar.
4. Add prompt-bar helpers that handle a TextArea undo/redo text transition and apply the matching transaction's
   frontmatter side effect.
5. Hook the existing NORMAL-mode `u` and `Ctrl+R` paths in `PromptTextArea` to notify the parent prompt bar after a real
   text change. Ordinary undo/redo edits with no matching xprompt transaction remain unchanged.
6. Remove or rewrite the old code comment that said staged inputs intentionally survive body undo.

## Tests

Add focused widget tests around the current `Ctrl+I` expansion coverage:

- Expanding an input-bearing xprompt stages the input; `Esc`, then `u`, restores the original body and removes the
  staged input from frontmatter.
- If that staged input was the only property, undo hides the frontmatter panel and clears `bar._stack.frontmatter`.
- If unrelated properties existed before expansion, undo removes only the expansion-added input and keeps the panel
  visible.
- If an input name already existed before expansion, undo does not remove that pre-existing declaration.
- Multiple inputs from one expansion are removed together.
- Multiple expansions are undone LIFO in one pane: the first `u` removes only the second expansion's staged inputs, and
  the next `u` removes the first expansion's staged inputs.
- Multi-pane/shared input: if a later active expansion still depends on an auto-staged input, undoing the original owner
  does not remove the shared declaration until the last dependent expansion is undone.
- `Ctrl+R` after undo reapplies the body expansion and restages the input declarations, without overwriting any
  user-authored declaration with the same name.
- Invalid/mid-edit frontmatter is not rewritten during the automatic unstage path.

## Verification

Run the focused tests first:

```bash
pytest tests/ace/tui/widgets/test_prompt_bar_xprompt_selector_targeting.py tests/ace/tui/widgets/test_prompt_input_bar_stack_editor.py tests/ace/tui/test_prompt_bar_xprompt_selector_requests.py
```

Then run the repo checks required for ACE changes:

```bash
just fmt
just check
```

## Acceptance Criteria

- `u` after a successful `Ctrl+I` inline expansion removes the properties that expansion added to the property panel.
- The property panel hides when no prompt properties remain after that undo.
- Existing/user-authored prompt properties are preserved.
- Redo restores the expansion body and its staged inputs.
- No synchronous I/O or broad TUI refresh path is added to undo/redo key handling.
