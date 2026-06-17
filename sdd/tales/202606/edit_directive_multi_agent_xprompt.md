---
create_time: 2026-06-17 07:30:28
status: done
prompt: sdd/prompts/202606/edit_directive_multi_agent_xprompt.md
---
# Plan: `%edit` Returns Multi-Agent XPrompt Markdown To The Prompt Stack

## Summary

Make `%edit` reliably mean "load the edited markdown back into ACE for review" even when the editor buffer is a
multi-agent xprompt markdown document with one or more standalone `---` segment separators.

The desired result is:

- The `%edit` / `%e` directive is stripped.
- The remaining editor markdown is not launched immediately.
- If it contains real multi-agent `---` segment separators outside fenced blocks and outside leading YAML frontmatter,
  ACE shows the prompt stack with one prompt input pane per agent segment.
- If the markdown has xprompt properties in leading YAML frontmatter, the existing frontmatter panel above the top
  prompt pane reflects those properties.
- Existing active-pane editor behavior remains intact: `Ctrl+G` in an already-stacked prompt edits only the active pane;
  `Ctrl+Shift+G` remains the explicit whole-stack editor.

## Current State

The infrastructure is mostly present:

- `%edit` detection lives in `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_mount.py` as `has_edit_directive()`.
  It delegates to `extract_prompt_directives()`, so fenced `%edit` examples are ignored and the returned prompt is
  cleaned consistently with launch-time directive stripping.
- `PromptInputBar` already supports multiple prompt panes through `PromptStackState`.
- `PromptStackState.from_text()` already uses the canonical multi-prompt parser, so `---` inside fenced code blocks and
  leading YAML frontmatter delimiters are not treated as agent separators.
- `PromptInputBar.load_stack_from_xprompt_markdown()` already has the right semantics for editor markdown: lift leading
  frontmatter into the stack/frontmatter panel and split body separators into prompt panes.
- `PromptInputBar.load_stack_from_text()` intentionally has a different history-load contract: a single prompt with
  frontmatter stays one verbatim pane unless real multi-prompt splitting is needed.

The likely gaps are routing and coverage:

- Some `%edit` editor-return paths still route through generic prompt-bar loading instead of explicitly using xprompt
  markdown semantics.
- `_select_and_open_editor_for_home()` strips `%edit` and remounts the prompt bar, but should preserve the
  display/history context supplied by the caller and should mount the cleaned editor text as xprompt markdown.
- `_start_prompt_history_from_last_selection()` has an edit-first helper that edits and launches directly; unlike other
  editor-return paths, it does not currently honor `%edit`.
- Existing tests cover `%edit` on active-pane editor returns and the whole-stack editor, but do not pin the requested
  "editor markdown with `%edit` plus multi-agent separators plus xprompt frontmatter" behavior.

## Behavior Contract

1. `%edit` is an editor-return control directive, not a launch directive for the edited prompt.
2. When `%edit` appears in the editor buffer returned from a markdown prompt file, the cleaned result is loaded back
   into the prompt bar using xprompt markdown semantics.
3. A cleaned editor buffer such as:

   ```markdown
   ---
   description: Review auth and API separately
   xprompts:
     _shared: Use the same style guide.
   ---

   ## Review auth.

   Review API.
   ```

   should produce two prompt panes and a visible frontmatter panel containing the `description` and local `xprompts`
   properties.

4. `%edit` without `---` still returns the cleaned text to the prompt bar for review. If the text has xprompt
   frontmatter, the editor-markdown path should lift it into the frontmatter panel rather than leaving it as literal
   pane text.
5. Editor returns without `%edit` keep current behavior:
   - single-pane `Ctrl+G` launches the edited text;
   - stacked `Ctrl+G` updates only the active pane;
   - `Ctrl+Shift+G` reloads the whole stack and never launches.
6. Ordinary history `LOAD` keeps its current `load_stack_from_text()` behavior. This plan should not silently
   reinterpret every historical single-prompt frontmatter block as structured xprompt markdown unless the user
   explicitly entered an editor-return path with `%edit`.

## Design

### 1. Centralize editor-markdown reloads

Add one small app-side helper near the prompt-bar mount/request code, for example:

- load cleaned editor markdown into an existing prompt bar via `PromptInputBar.load_stack_from_xprompt_markdown()`;
- or mount a new prompt bar whose initial state is created from xprompt markdown semantics.

This helper should be used only for `%edit` editor returns and whole-stack editor returns. It should not replace
ordinary history-load behavior.

If constructor support is needed, extend `PromptInputBar` with an explicit `initial_xprompt_markdown` / `initial_kind`
style option rather than overloading `initial_value`. That keeps the existing distinction clear:

- `initial_value`: normal prompt text / history-load semantics;
- `initial_panes`: one verbatim pane per prompt, used by bulk kill-and-edit;
- `initial_xprompt_markdown`: editor file semantics, including frontmatter lifting and `---` splitting.

### 2. Route all `%edit` editor returns through that helper

Update the editor-return paths that already call `has_edit_directive()`:

- `PromptBarRequestsMixin.on_prompt_input_bar_editor_requested()` for the single-pane `%edit` case.
- `PromptBarRequestsMixin.on_prompt_input_bar_history_requested()` for "edit first" results from the prompt history
  modal.
- `PromptBarMountMixin._select_and_open_editor_for_home()` for direct editor-first launches from project/home/VCS
  selection.

Keep the stacked active-pane `Ctrl+G` path intentionally pane-local: if the bar was already stacked before opening the
editor on one pane, `%edit` should continue to strip and update that one pane rather than reinterpret the returned text
as a whole-stack document. The user already has `Ctrl+Shift+G` for whole-stack editing.

### 3. Preserve launch context when `%edit` remounts the bar

When `_select_and_open_editor_for_home(initial_text=..., display_name=..., history_sort_key=...)` receives `%edit`, it
should remount the prompt bar using the same `display_name` and `history_sort_key` supplied by the caller. That prevents
the review bar from falling back to generic home labels after a VCS/project selection.

The same principle applies to the prompt-history-last-selection path: if `%edit` requests review instead of launch, keep
the context that would have been used for the launch.

### 4. Add focused regression coverage

Add tests at three levels:

- Pure/widget stack coverage:
  - xprompt markdown with frontmatter and two body segments loads into two panes;
  - the frontmatter panel is visible and reflects the lifted properties;
  - fenced `---` remains protected.
- Prompt-bar request coverage:
  - single-pane editor return with `%edit`, frontmatter, and `---` reloads the bar as xprompt markdown and does not call
    `_finish_agent_launch()`;
  - stacked active-pane `Ctrl+G` keeps current pane-local behavior.
- Entry-point coverage:
  - `_select_and_open_editor_for_home()` with a `%edit` multi-agent markdown result mounts a prompt bar for review, does
    not launch, and preserves caller display/history context;
  - `_start_prompt_history_from_last_selection(edit_first=True)` honors `%edit` instead of launching the cleaned prompt.

Existing tests to extend are likely:

- `tests/ace/tui/test_prompt_bar_editor_stack.py`
- `tests/ace/tui/widgets/test_prompt_input_bar_stack.py`
- `tests/ace/tui/test_entry_points_vcs_prefix_errors.py`

### 5. Documentation

Update the `%edit` section in `docs/xprompt.md` to mention that editor markdown containing multi-agent `---` separators
is returned to the ACE prompt stack, and leading xprompt frontmatter appears in the prompt properties panel.

## Verification

Run focused tests first:

```bash
pytest tests/ace/tui/test_prompt_bar_editor_stack.py \
  tests/ace/tui/widgets/test_prompt_input_bar_stack.py \
  tests/ace/tui/test_entry_points_vcs_prefix_errors.py
```

Because this repo requires it after source changes:

```bash
just install
just check
```

## Risks And Boundaries

- Do not change core multi-prompt parsing unless a test proves the parser itself is wrong. The existing Rust-backed
  split path is the right boundary for shared separator semantics.
- Do not collapse the three prompt-bar seeding modes (`initial_value`, `initial_panes`, editor xprompt markdown). They
  represent different product contracts and should stay explicit.
- Be careful with `Ctrl+G` on an existing stack: changing it to whole-stack semantics would regress the recently-added
  active-pane editor contract.
- Frontmatter parsing requires the YAML block to start the cleaned markdown. `%edit` stripping should continue to remove
  its own line cleanly before markdown loading.
