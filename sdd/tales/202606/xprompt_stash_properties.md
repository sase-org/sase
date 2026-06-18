---
create_time: 2026-06-18 12:03:39
status: done
prompt: sdd/prompts/202606/xprompt_stash_properties.md
---
# Preserve xprompt properties through prompt stash bundles

## Goal

Make `gS` and `<ctrl+g>S` preserve xprompt properties authored in the prompt input widget's xprompt properties panel,
and make `gp` / `gP` restore those same properties into the prompt bar as structured prompt frontmatter.

## Current understanding

Prompt properties are stored on `PromptStackState.frontmatter`, not on individual prompt panes. The `FrontmatterPanel`
edits a `PromptFrontmatter` model and persists it back to that shared frontmatter string.

The stash store already has a `PromptStashEntryWire.frontmatter` field, so this should not require a wire-schema or Rust
store migration. For `gS`, the TUI posts one `PromptInputBar.Stashed` event with all non-empty panes, and the app
persists those panes as one bundle row whose `text` is the panes joined with `---`.

The current restore path already expands bundle rows back into pane tuples, but two edges need tightening:

- Restoring into an already-mounted empty prompt bar adopts stash frontmatter on the stack, but does not explicitly
  re-sync/show the visible frontmatter panel.
- Restoring with no mounted bar uses ordinary `initial_value` semantics. For multi-pane bundles this usually lifts
  frontmatter, but stash restore is semantically xprompt markdown and should use that path explicitly, including
  single-pane edge cases.

Existing tests cover generic frontmatter on `gS`, but not local `xprompts:` authored through the properties panel, and
not the visible property-panel state after restore.

## Plan

1. Add regression coverage for panel-authored xprompt properties during capture.
   - Use the existing Textual prompt-bar test harness.
   - Create local `xprompts:` via the Frontmatter Panel sub-editor, then invoke `gS` and `<ctrl+g>S`.
   - Assert every captured `StashedPromptPane.frontmatter` contains the canonical `xprompts:` block and the local helper
     name/content.

2. Keep persistence on the existing bundle row shape.
   - Continue storing `gS` as one `PromptStashEntryWire` bundle row.
   - Ensure the row's `frontmatter` is the live shared stack frontmatter from the capture event.
   - Add an app-handler regression that persists a bundle with canonical frontmatter delimiters and a local `xprompts:`
     property, then reads the row back from the store.

3. Restore stash frontmatter as xprompt markdown.
   - When there is no mounted prompt bar, load restored stash text with `as_xprompt_markdown=True` so frontmatter is
     lifted into `PromptStackState.frontmatter` instead of remaining as verbatim body text.
   - When restoring into a mounted prompt bar that has no frontmatter, keep the existing "first restored frontmatter
     wins" behavior, then call the existing `refresh_frontmatter_panel_from_stack()` hook so the panel shows/syncs the
     restored properties.
   - Preserve the current behavior when the destination bar already has frontmatter: do not silently overwrite
     in-progress draft properties. The prompt stack has only one shared frontmatter block, so mixing two conflicting
     frontmatter sets cannot be represented safely without a separate conflict UI.

4. Add restore regression coverage.
   - Extend widget restore tests to assert restored local `xprompts:` are visible through the stack model and the
     Frontmatter Panel after `restore_stashed_entries()`.
   - Extend app restore tests so no-bar restore calls the home prompt mount with xprompt-markdown semantics.
   - Include a single-row/single-body edge case where frontmatter would otherwise stay inline under ordinary
     history-load semantics.

5. Verify.
   - Use the repo test runner rather than ambient `pytest`; the ambient interpreter in this workspace is missing Textual
     and `pytest-asyncio`.
   - Run targeted tests through `just test` for the prompt stash and frontmatter suites.
   - Because this changes repo files, finish with `just check` after implementation.

## Files likely touched

- `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py`
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`
- `tests/ace/tui/widgets/test_prompt_stash_capture.py`
- `tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py`
- `tests/ace/tui/actions/test_prompt_stash_handler.py`
- `tests/ace/tui/actions/test_prompt_stash_restore.py`

## Non-goals

- No keymap changes.
- No prompt-stash wire schema migration.
- No attempt to merge conflicting frontmatter blocks when restored entries are appended to a prompt bar that already has
  different properties.
