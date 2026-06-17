---
create_time: 2026-06-17 13:19:38
status: done
prompt: sdd/prompts/202606/prompt_editor_spacing.md
---
# Plan: Prompt Editor Markdown Spacing

## Context

The ACE prompt input bar now supports opening a multi-pane prompt stack in the user's editor with `<ctrl+g>`. That path
serializes the live prompt stack through `PromptInputBar.xprompt_markdown_for_editor()` before suspending the TUI and
opening the temporary markdown file.

Today that serialization reuses `PromptStackState.join()`, which produces the launch/history form:

```markdown
## first prompt

second prompt
```

and, when prompt-level YAML frontmatter exists:

```markdown
---
model: opus
---

## first prompt

second prompt
```

That is compact and compatible with dispatch, but it is not the editor-friendly format requested here. The launch path
should remain byte-stable unless there is a product reason to change it; this request is specifically about the markdown
file opened in the user's editor.

## Desired Behavior

When constructing the markdown buffer for the whole-stack `<ctrl+g>` editor:

- Agent prompt separator lines should be surrounded by blank lines:

```markdown
first prompt

---

second prompt
```

- If prompt-level frontmatter is present, the first prompt body should start after a blank line following the closing
  frontmatter delimiter:

```markdown
---
model: opus
---

first prompt

---

second prompt
```

The parser/reload path should continue accepting this spaced markdown and reconstructing the prompt stack normally.

## Design

Add an editor-only serialization surface instead of changing `PromptStackState.join()`.

`join()` is used by whole-stack submit, current prompt text, history/cancel recording, and several tests that pin the
compact canonical launch form. Changing it would broaden the behavior change beyond the editor file. A dedicated
editor-markdown method keeps product behavior scoped to `<ctrl+g>` while making the formatting contract explicit.

The most natural home is the non-visual `PromptStackState` model, because it already owns split/join semantics and
frontmatter reattachment. A method such as `editor_markdown()` can:

- sync with the same non-empty, stripped pane selection semantics as `join()`;
- join prompt bodies with `\n\n---\n\n`;
- reattach non-empty frontmatter with `\n\n` between the closing frontmatter delimiter and the body;
- return only the frontmatter when there are no non-empty prompt bodies, matching the existing empty-body behavior.

Then `PromptInputBar.xprompt_markdown_for_editor()` should call that editor-only method after syncing live widgets into
the stack.

## Test Plan

Add focused unit coverage in `tests/ace/tui/widgets/test_prompt_stack.py` for the new editor serialization contract:

- multi-pane stack without frontmatter renders `\n\n---\n\n` between prompts;
- prompt-level frontmatter renders with a blank line before the first body;
- empty panes are still dropped, matching `join()` semantics;
- frontmatter-only output remains just the frontmatter block, with no trailing blank body spacer.

Update `tests/ace/tui/test_prompt_bar_editor_stack.py` so the all-editor handler asserts that `<ctrl+g>` opens the
spaced editor markdown while reloading edited markdown remains unchanged.

Run the targeted tests first:

```bash
pytest tests/ace/tui/widgets/test_prompt_stack.py tests/ace/tui/test_prompt_bar_editor_stack.py
```

Because source/test files will be changed in this repo, finish with the required repo check:

```bash
just install
just check
```

## Out Of Scope

Do not change the compact launch payload returned by `current_prompt_text()` or `PromptStackState.join()`.

Do not change multi-prompt parsing rules. Existing parsing already handles blank lines around separator lines by
dropping empty/whitespace-only segments.

Do not change keymaps or default config.
