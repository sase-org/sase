---
create_time: 2026-04-01 14:25:19
status: done
prompt: sdd/prompts/202604/edit_directive.md
---

# Plan: `%edit` (`%e`) Directive

## Problem

When composing prompts in the external editor (Ctrl+G), the only outcome is launching an agent. There's no way to return
the edited text back to the inline prompt input widget for further refinement. This forces an all-or-nothing workflow:
either the editor text launches an agent, or you cancel and lose the text.

## Solution

Add a new `%edit` (`%e`) directive. When present in a prompt returned from the editor, the directive is stripped and the
cleaned prompt is loaded into the prompt input widget instead of launching an agent.

## Design Decisions

**TUI-only directive, not a runtime directive.** Unlike `%model` or `%name`, `%edit` is consumed entirely at the TUI
layer — it never reaches the agent runner or LLM invocation. This means:

- It gets added to `_KNOWN_DIRECTIVES` and `_DIRECTIVE_ALIASES` so the standard parser recognizes and strips it.
- It gets a field on `PromptDirectives` so callers can check for it.
- But it's checked and consumed in the TUI prompt bar handlers, before `_finish_agent_launch` is ever called.

**Works at all editor return points.** There are three code paths where editor output flows to `_finish_agent_launch`:

1. `on_prompt_input_bar_editor_requested` — Ctrl+G from prompt bar (bar is still mounted)
2. `_select_and_open_editor_for_home` — Direct editor for home mode (no bar mounted)
3. History picker EDIT action — Editor opened from history modal (bar is still mounted)

For paths 1 and 3, the prompt bar is already mounted, so we load text directly into it. For path 2, we need to mount a
prompt bar first (switching from the "direct editor" flow to the "show bar with pre-populated text" flow).

**Not meaningful from inline submit.** If a user types `%edit` directly in the prompt bar and hits Enter, that's
contradictory — they're already in the widget. We should strip it silently and proceed with the launch as normal, since
the user explicitly submitted. The directive only changes behavior when returning from an external editor.

## Implementation

### Phase 1: Directive Parsing (`src/sase/xprompt/directives.py`)

1. Add `"edit"` to `_KNOWN_DIRECTIVES`.
2. Add `"e": "edit"` to `_DIRECTIVE_ALIASES`.
3. Add `edit: bool = False` field to `PromptDirectives`.
4. Set `edit="edit" in expanded_args` in the `PromptDirectives` constructor at the end of `extract_prompt_directives`.

### Phase 2: TUI Prompt Bar Handlers (`src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`)

Add a helper method `_has_edit_directive(prompt: str) -> tuple[bool, str]` that does a quick regex check for `%edit` /
`%e` (similar to `has_wait_directive`), and if found, runs `extract_prompt_directives` to get the cleaned prompt.
Returns `(True, cleaned_prompt)` or `(False, original_prompt)`.

Then add a helper `_load_prompt_into_bar(prompt: str)` that finds the mounted bar and calls `load_text` on its text
area. This consolidates the pattern already used in the history LOAD path.

Update the three editor return points:

1. **`on_prompt_input_bar_editor_requested`** (line ~357): Before calling `_finish_agent_launch`, check for `%edit`. If
   found, call `_load_prompt_into_bar(cleaned)` instead.

2. **`_select_and_open_editor_for_home`** (line ~252): Before calling `_finish_agent_launch`, check for `%edit`. If
   found, call `_show_prompt_input_bar_for_home(initial_text=cleaned)` to mount a bar with the text.

3. **History EDIT action** (line ~420): Before calling `_finish_agent_launch`, check for `%edit`. If found, call
   `_load_prompt_into_bar(cleaned)` instead.

### Phase 3: Tests (`tests/test_directives.py`)

Add tests for the directive parsing:

- `%edit` is recognized and stripped, `directives.edit == True`
- `%e` alias works
- `%edit` inside fenced code blocks is ignored
- Duplicate `%edit` raises `DirectiveError`

### Phase 4: Lint and Check

Run `just install && just check` to verify everything passes.
