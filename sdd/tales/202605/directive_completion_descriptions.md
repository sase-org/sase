---
create_time: 2026-05-07 11:47:54
status: done
prompt: sdd/prompts/202605/directive_completion_descriptions.md
---
# Plan: Directive Completion Descriptions

## Goal

Add a concise description for each prompt directive shown by the `<ctrl+t>` directive completion menu. The menu should
continue to behave exactly as it does today for filtering, shared-prefix completion, navigation, and acceptance; this is
a presentation/data enrichment change, not a directive parsing change.

## Current State

Recent commit `53a1d122 feat: add prompt directive completion` added a TUI-only directive completion path:

- `src/sase/ace/tui/widgets/directive_completion.py` builds directive candidates from `_KNOWN_DIRECTIVES | {"alt"}`.
- `DirectiveCompletionMetadata` currently carries aliases and an argument hint.
- `src/sase/ace/tui/widgets/prompt_input_bar.py` renders directive candidates as `%directive`, then dim argument/alias
  details.
- `src/sase/ace/tui/widgets/_file_completion.py` dispatches `%...` tokens to this builder before generic file/xprompt
  token handling.
- `tests/ace/tui/widgets/test_directive_completion.py` covers candidate building and prompt-widget integration.

The source of truth for parser behavior remains `sase.xprompt._directive_types` and `sase.xprompt._directive_alt`.
Descriptions are UI help text, so they should stay in the TUI completion layer unless a future CLI/LSP/API completion
surface needs shared metadata.

## Design

Extend the existing completion metadata shape instead of adding a parallel registry:

- Add `description: str = ""` to `DirectiveCompletionMetadata`.
- Add a `_DIRECTIVE_DESCRIPTIONS` mapping in `directive_completion.py`, adjacent to `_DIRECTIVE_ARGUMENT_HINTS`.
- Populate every user-facing directive currently emitted by completion:
  - `alt`: split a prompt into text/model variants.
  - `approve`: run autonomously without plan approval prompts.
  - `edit`: return editor text to the prompt bar before launch.
  - `epic`: plan first and auto-approve the plan as an epic.
  - `hide`: hide the agent from the default Agents tab.
  - `model`: choose one or more provider/model targets.
  - `name`: assign or auto-generate the agent name.
  - `plan`: create a plan first, then wait for approval.
  - `repeat`: run the prompt multiple serial iterations.
  - `tag`: assign a user-managed agent tag.
  - `wait`: defer launch until agents complete or time elapses.

Keep the text short enough for a terminal completion row. Use wording aligned with `docs/xprompt.md`, but store the
descriptions in code so the completion menu has no runtime dependency on docs parsing.

Render the description in `_append_directive_completion_row()` after the existing argument hint and alias details:

- Keep `%directive` as the first visual anchor.
- Keep argument hint and aliases in dim metadata.
- Append the description as dim metadata in the same row, separated like the existing details.
- Do not alter iconography, selection behavior, row count, or border title.

This preserves the menu's current compact single-row-per-candidate layout. If the row becomes visually too wide in
practice, a later change can prioritize or truncate metadata, but the first pass should stay simple and consistent with
the existing xprompt/directive row rendering.

## Tests

Update focused tests rather than broad TUI snapshots:

- Extend candidate-builder tests to assert representative descriptions are present for `%model`, `%wait`, and `%alt`.
- Add a test that every candidate returned for `%` has a non-empty description, preventing new user-facing directives
  from silently appearing without help text.
- Add or extend a prompt-bar rendering test so a directive completion panel includes the description text in the
  rendered `Static` content.
- Keep existing alias and acceptance tests unchanged except for any helper assertions needed around metadata.

## Verification

After implementation:

1. Run `just install` if the workspace environment is not already prepared.
2. Run targeted tests: `pytest tests/ace/tui/widgets/test_directive_completion.py`.
3. Run `just check` before final handoff, as required by this repo after non-bead file changes.

## Risks

- Description wording can drift from docs if future directive semantics change. The guardrail is to keep the mapping
  directly beside the completion argument hints and require non-empty descriptions for all completion candidates.
- Terminal width can make long metadata noisy. The descriptions should be concise, and rendering should reuse the
  existing dim details style rather than creating multi-line rows.
- `%alt` is not in `_KNOWN_DIRECTIVES`, so any completeness test must exercise the actual completion candidate list, not
  only parser directives.
