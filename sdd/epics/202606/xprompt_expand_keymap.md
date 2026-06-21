---
create_time: 2026-06-21 10:43:06
status: done
prompt: sdd/prompts/202606/xprompt_expand_keymap.md
bead_id: sase-53
tier: epic
---
# Plan: Ctrl+I XPrompt Expansion From Select XPrompt

## Goal

Add a `Ctrl+I` keymap to the `Select XPrompt` panel opened by typing `#@` in a prompt input pane.

The new keymap should expand the highlighted xprompt directly into the originating prompt input pane. It should:

- Replace the `#` trigger that opened the panel, not append elsewhere.
- Preserve all other text in that pane.
- Leave every other prompt pane untouched.
- Include local xprompts declared through the prompt xprompt property panel.
- Show a user-facing error and keep the selector open when expansion is not possible.
- Make a successful expansion undoable with the prompt normal-mode `u` keymap.

Existing `Enter` behavior should remain unchanged: it inserts the selected xprompt reference.

## Current Code Shape

Relevant implementation surfaces:

- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py`
  - Detects `#@` before `@` is inserted and posts `PromptInputBar.SnippetRequested`.
- `src/sase/ace/tui/widgets/_prompt_input_bar_messages.py`
  - `SnippetRequested` currently carries no origin information.
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_requests.py`
  - Handles `SnippetRequested`, builds `XPromptSelectModal`, and currently re-queries `#prompt-input-bar` in the modal
    callback.
- `src/sase/ace/tui/modals/xprompt_select_modal.py`
  - Shows the selector, loads unified `Workflow` entries via `get_all_prompts()`, and returns `XPromptSelection` for
    insertion.
- `src/sase/ace/tui/widgets/_prompt_input_bar_actions.py`
  - `insert_snippet()` mutates the active `PromptTextArea` via `_replace_via_keyboard()`.
- `src/sase/ace/tui/widgets/_prompt_input_bar_frontmatter.py`
  - Exposes local frontmatter xprompts for completion.
- `src/sase/xprompt/processor.py`
  - Expands `XPrompt` references and supports recursive local xprompts, but its public function exits on some errors.
- `src/sase/xprompt/workflow_models.py`
  - Classifies selector entries as simple xprompt, embeddable workflow, or standalone workflow.

Important constraints:

- Do not rebuild the prompt stack for a plain expansion. Rebuilding loses the natural `TextArea` undo behavior.
- Use the active pane's existing `_replace_via_keyboard()` path so `u` can undo the expansion.
- Avoid synchronous heavy work on the TUI event loop. The selected workflow is already loaded by the modal, but any
  catalog expansion or parsing that can touch disk should be kept small, cached, or moved off the key handler path.
- Do not add an app-wide configurable keymap unless this becomes an app-level binding. `Ctrl+I` is modal-local.

## Expansion Semantics

For the first implementation, treat the selected catalog entry by `Workflow.prompt_kind()`:

- Simple xprompt: supported. Render its `prompt_part` content as inline text.
- Pure prompt-part workflow with no pre/post steps, environment, or runtime side effects: supported only if it can be
  rendered through the same safe helper as simple xprompts.
- Embeddable workflow with pre/post steps, environment, bash/python/agent steps, or other runtime side effects: not
  supported from `Ctrl+I`; show an error and keep the modal open.
- Standalone workflow: not supported from `Ctrl+I`; show an error and keep the modal open.
- Required inputs without provided values: not supported from `Ctrl+I`; show an error explaining that the reference can
  be inserted instead.

Rendering should preserve the full selected xprompt body. If the body contains `---` segment separators, insert them as
text in the active pane rather than splitting/rebuilding panes. Launch-time parsing already owns the meaning of those
separators.

Expansion must use local xprompts from the live prompt frontmatter as extra xprompts so a selected local helper or a
globally selected xprompt that references a local helper expands the same way it would at launch.

## Phase 1: Targeted Prompt Pane Plumbing

Owner: Agent 1

Objective: make `#@` selector actions target the exact pane that opened the selector.

Implementation work:

- Extend `PromptInputBar.SnippetRequested` to carry an explicit origin:
  - the originating `PromptInputBar` or enough identity to find it,
  - the originating `PromptTextArea` or stable pane id,
  - the captured trigger range covering the literal `#` that opened `#@`.
- Update `_prompt_text_area_key_handling.py` to populate that origin when it detects `#@`.
- Update `_prompt_bar_requests.py` so insertion no longer re-queries generic `#prompt-input-bar` after the modal closes.
- Keep existing `Enter` insertion behavior intact by inserting into the captured target and replacing only the suffix
  range after the `#`.
- Add a small target-staleness guard. If the original pane or bar has been unmounted before the user selects, notify and
  leave the prompt unchanged.

Edge cases to cover:

- Single prompt pane with empty text: `#@` then `Enter` still inserts `#name`.
- Prompt pane with surrounding text: `before #@ after` inserts at the original `#`.
- Multi-pane stack: opening `#@` from an upper pane and then selecting affects only that upper pane.
- Existing callback behavior still works for project-local prompts loaded from a VCS tag.

Suggested tests:

- Add widget tests under `tests/ace/tui/widgets/` for selector-origin targeting.
- Add or update modal/request tests near `tests/ace/tui/test_prompt_bar_history_requests.py` or create a focused
  `test_prompt_bar_xprompt_selector_requests.py`.

## Phase 2: Safe Inline Expansion Helper

Owner: Agent 2

Objective: add pure, testable logic that decides whether a selected entry can be expanded and returns either expanded
text or a user-facing error.

Implementation work:

- Add a small helper module near the TUI/xprompt boundary, for example
  `src/sase/ace/tui/widgets/xprompt_inline_expansion.py` or `src/sase/ace/tui/util/xprompt_inline_expansion.py`.
  The public entry point is `expand_inline_xprompt(name, workflow, *, local_xprompts, project)`, consumed by the
  Phase 3 modal callback in `_prompt_bar_requests.py`.
- Define a typed result such as `InlineExpansionResult` with:
  - `expanded_text: str | None`
  - `error: str | None`
  - optional `reason_code` for tests (an `InlineExpansionReason` enum).
- Input should include:
  - selected name,
  - selected `Workflow`,
  - local xprompts from prompt frontmatter,
  - optional project if needed for catalog parity.
- Reuse existing parser/rendering primitives instead of duplicating xprompt syntax:
  - convert simple prompt-part workflows to an `XPrompt` where appropriate,
  - use `expand_single_xprompt()` or `process_xprompt_references_with_catalog()` for recursive expansion,
  - catch `XPromptError`, `XPromptValidationError`, `WorkflowValidationError`, and `SystemExit` from legacy expansion
    paths and return a clean error string.
- Reject unsupported workflow kinds with explicit messages:
  - standalone workflow: "Cannot inline-expand #!name because it is a workflow. Press Enter to insert the reference."
  - embeddable workflow with runtime steps: "Cannot inline-expand #name because it has workflow steps."
  - required input missing: "Cannot inline-expand #name because input 'foo' is required."

Edge cases to cover:

- Simple no-arg xprompt expands to content.
- Simple xprompt with defaults expands using defaults.
- Simple xprompt with required inputs returns an error.
- Nested local xprompt references expand when provided through frontmatter.
- Circular or invalid xprompt expansion returns an error rather than exiting the app.
- Standalone and side-effectful YAML workflows return errors.

Suggested tests:

- Add unit tests under `tests/ace/tui/widgets/` or `tests/ace/tui/` for the helper.
- Prefer direct helper tests over full Textual tests for error and workflow classification behavior.

## Phase 3: Modal Ctrl+I Action And User Feedback

Owner: Agent 3

Objective: wire `Ctrl+I` into `XPromptSelectModal` without changing `Enter` behavior.

Implementation work:

- Add `("ctrl+i", "expand_selected", "Expand")` to both:
  - `XPromptSelectModal.BINDINGS`,
  - `_XPromptFilterInput.BINDINGS` via the existing `forward(...)` pattern.
- Update the modal hint text to mention `^i: expand`.
- Give the modal a narrow expansion callback supplied by `_prompt_bar_requests.py`.
  - The callback receives the selected name/workflow and returns success or an error message.
  - On success, the modal dismisses without returning an insertion payload.
  - On error, the modal calls `notify(..., severity="error")` and remains open.
- Add `action_expand_selected()` to:
  - find the selected item with `_selected_name()`,
  - guard empty/no selection,
  - call the expansion callback,
  - preserve filter/highlight state on errors.

Edge cases to cover:

- `Ctrl+I` from the filter input works.
- `Ctrl+I` with no matches warns and keeps the modal open.
- Unsupported workflow errors keep the modal open.
- Successful expansion closes the modal and does not also insert a reference through the normal callback.
- `Ctrl+E` open-definition behavior still works.

Suggested tests:

- Extend `tests/ace/tui/modals/test_xprompt_select_modal.py`.
- Use the existing `_TestApp.notifications` pattern to assert error notifications and non-dismissal.

## Phase 4: Apply Expansion To Prompt Text With Undo

Owner: Agent 4

Objective: make successful expansion mutate the originating prompt pane as one undoable edit.

Implementation work:

- Add a method on `PromptInputBar`, for example `expand_xprompt_at_target(target, expanded_text)`.
- The method should:
  - validate target freshness,
  - clear transient completion/soft-completion/xprompt-hint state for the active target,
  - replace the captured trigger range covering the literal `#` with `expanded_text` using
    `PromptTextArea._replace_via_keyboard()`,
  - put the cursor at the end of the inserted text,
  - refocus the originating text area,
  - keep the pane's current vim mode reasonable, matching current snippet insertion behavior.
- Do not call `load_stack_from_text()`, `load_stack_from_xprompt_markdown()`, or `_rebuild_stack()` for this operation.
- If the expansion includes newlines, rely on existing `TextArea.Changed` handling to resize the bar and line-number
  state.

Undo contract:

- After expansion, pressing `Esc` then `u` should restore the exact pre-expansion prompt text, including the literal `#`
  trigger.
- Other panes and prompt frontmatter must remain unchanged.

Edge cases to cover:

- Empty pane: `#@` expands to body, `u` restores `#`.
- Surrounding text: `before #@ after` expands to `before BODY after`, `u` restores `before # after`.
- Multi-line body: one undo returns to the original one-line or multi-line text.
- Multi-pane active upper pane: expansion and undo affect only that pane.
- Existing text in other prompt panes remains byte-for-byte unchanged.

Suggested tests:

- Add widget-level Textual tests with `PromptInputBar` and `PromptTextArea`.
- Include at least one test that drives the actual `#@` key sequence, chooses `Ctrl+I`, then exits to normal mode and
  presses `u`.

## Phase 5: Local XPrompts And Project Catalog Parity

Owner: Agent 5

Objective: ensure xprompts from the prompt property panel and project-local catalog are visible and expandable.

Implementation work:

- In `_prompt_bar_requests.py`, when building `extra_prompts` for `XPromptSelectModal`, merge sources in the same
  priority order the UI should expose:
  - project-local prompts detected from the leading VCS tag,
  - live frontmatter `xprompts:` from `PromptInputBar._stack.frontmatter`, converted with `xprompt_to_workflow()`.
- Reuse `PromptFrontmatter.parse()` or an existing prompt-bar helper to avoid ad hoc YAML parsing.
- Make local xprompts available to the Phase 2 expansion helper as real `XPrompt` objects, not only as display-only
  `Workflow` projections.
- If frontmatter is invalid or contains invalid local xprompt names, do not crash. Notify only when the user directly
  selects or expands an invalid local entry; otherwise omit invalid local entries from the selector.

Edge cases to cover:

- A local `_rules` xprompt authored through the property panel appears in `#@`.
- `Ctrl+I` on `_rules` expands its content.
- A global xprompt that references `_rules` expands recursively when `_rules` exists in frontmatter.
- If another pane has text, local expansion in the active pane leaves it unchanged.
- Project-local prompts from a VCS tag still appear after adding frontmatter locals.

Suggested tests:

- Build on `tests/ace/tui/widgets/test_frontmatter_panel_subeditors.py`.
- Add a focused selector test that mounts a prompt bar with frontmatter and verifies both selector catalog and
  expansion.

## Phase 6: Regression, Performance, And Documentation Pass

Owner: Agent 6

Objective: close gaps across tests, hints, and performance assumptions.

Implementation work:

- Audit updated hints:
  - selector footer hint includes `^i: expand`,
  - no stale hint says only Enter can select.
- Confirm no default app keymap config changes are needed. If a phase introduced app-wide keymap registry changes,
  update `src/sase/default_config.yml` and keymap tests.
- Check that the expansion path does not do repeated full catalog loads on every selector navigation. Expansion should
  run only on explicit `Ctrl+I`.
- Add a short comment only where the callback/target lifetime is non-obvious.

Verification commands:

- Run focused tests first:
  - `pytest tests/ace/tui/modals/test_xprompt_select_modal.py`
  - `pytest tests/ace/tui/widgets/test_prompt_stack_keymaps_add_pane.py tests/ace/tui/widgets/test_prompt_stack_keymaps_focus.py`
  - any new xprompt expansion tests added by earlier phases.
- Then run:
  - `just install`
  - `just check`

If only the plan file exists and no implementation changes have been made, `just check` is not required. Once source
changes begin, follow the repo instruction to run `just check` before handing off.

## Acceptance Criteria

- Typing `#@`, highlighting a supported xprompt, and pressing `Ctrl+I` expands the xprompt in the same prompt pane that
  opened the selector.
- Existing text before and after the trigger is preserved.
- Other prompt panes are unchanged.
- Local xprompts from the xprompt property panel can be selected and expanded.
- Unsupported YAML workflows and missing-input xprompts show an error without closing the selector.
- Successful expansion closes the selector and refocuses the originating pane.
- `Esc` then `u` after a successful expansion restores the prompt text from before expansion.
- Existing `Enter` insertion behavior and `Ctrl+E` open-definition behavior are unchanged.
