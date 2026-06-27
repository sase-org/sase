---
create_time: 2026-06-27 07:39:15
status: done
prompt: sdd/prompts/202606/local_xprompt_keymaps.md
---
# Plan: Prompt Input `gX` / `Ctrl+G X` Local XPrompt Conversion

## Goal

Add prompt-local keymaps:

- NORMAL mode: `gX`
- INSERT mode: `Ctrl+G` then `X`

These convert the active prompt input pane into a local xprompt stored in the prompt bar's shared frontmatter
`xprompts:` property, then replace that pane with an invocation of the new local helper.

Assumption: "current prompt input widget" means the active `PromptTextArea` pane inside the `PromptInputBar`, not the
entire multi-pane stack. Other panes should remain unchanged, while the new local xprompt is stored in the shared
frontmatter so any pane can reference it.

## Existing Architecture To Reuse

- Prompt-local `g` / `Ctrl+G` continuations are declared in
  `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py` via `_PROMPT_G_PREFIX_BINDINGS`.
- NORMAL `g...` dispatch goes through `src/sase/ace/tui/widgets/_vim_normal_pending.py`.
- INSERT and NORMAL `Ctrl+G ...` dispatch goes through `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py`.
- The frontmatter panel and shared prompt frontmatter state live in:
  - `src/sase/ace/tui/widgets/_prompt_input_bar_frontmatter.py`
  - `src/sase/ace/tui/widgets/frontmatter_panel.py`
  - `src/sase/xprompt/prompt_frontmatter.py`
- Local xprompt model objects already use `sase.xprompt.models.XPrompt` and are serialized by
  `PromptFrontmatter.set_xprompt()` / `PromptFrontmatter.serialize()`.
- Jinja variable inspection should reuse `src/sase/xprompt/jinja_inspect.py`, not regex parsing.
- Do not reuse the existing `gx` app-level save flow in
  `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt.py`; that flow writes global/project xprompt files
  and offers git commits, while this feature is local frontmatter-only.

## UX Contract

1. User triggers `gX` in NORMAL mode or `Ctrl+G X` in INSERT mode while a prompt pane is focused.
2. If the active pane is blank, show a warning toast and leave state unchanged.
3. Prompt for a local xprompt name.
   - The user can type `rules`; the stored name becomes `_rules`.
   - If the user types `_rules`, normalize to `_rules`, not `__rules`.
   - Validate through the same local xprompt underscore/name rules used by `XPromptItemModal`.
   - Reject duplicates against existing local `xprompts:` entries rather than silently overwriting.
4. Infer local xprompt inputs from undeclared Jinja variables in the active pane body.
   - Use `jinja_inspect.inspect_template()` / `unknown_variables()` with the known top-level context so globals like
     `root` are not added as inputs.
   - Each inferred input should be `InputArg(name=<var>, type=InputType.TEXT)`, with no default.
   - If Jinja syntax is invalid, leave the pane unchanged and notify the user rather than creating a helper with
     unreliable inputs.
5. Add `XPrompt(name="_rules", content=<old pane text>, inputs=<inferred inputs>, source_path=LOCAL_XPROMPT_SOURCE)` to
   the prompt bar's shared `PromptFrontmatter.xprompts`.
6. Refresh/show the frontmatter panel so the new `xprompts:` property is visible above the prompt stack, without leaving
   focus trapped in the panel.
7. Replace only the active pane text with a valid invocation:
   - No inferred inputs: `#_rules`
   - Inferred inputs: named-argument skeleton, e.g. `#_rules(topic=$1, details=$2)$0`, expanded through the existing
     snippet expansion engine so the visible pane becomes `#_rules(topic=, details=)` with tabstops.
8. Preserve the prompt stack structure and selected pane. For generated argument slots, leave the pane in INSERT mode so
   the user can immediately fill values; otherwise preserve the caller's target mode where practical.

## Implementation Steps

1. Add a small local-name modal or adapt a reusable name modal for this local-only flow.
   - Prefer a dedicated modal, e.g. `src/sase/ace/tui/modals/local_xprompt_name_modal.py`, because the existing
     `XPromptNameModal` is tied to file-save locations.
   - Export it from `src/sase/ace/tui/modals/__init__.py`.

2. Add pure helper functions for conversion decisions.
   - Name normalization and validation.
   - Jinja input inference.
   - Invocation skeleton generation from a local xprompt name and inferred inputs.
   - Keep these either near the prompt-bar action or in a small helper module so unit tests can cover them without a
     Textual app.

3. Add a new prompt-stack action.
   - Extend `_PROMPT_G_PREFIX_BINDINGS` with key `"X"`, action like `convert_active_pane_to_local_xprompt`, label like
     `"save as local xprompt"`, availability gated to prompt mode with non-blank active pane text.
   - Mark it `uses_target_mode=True` so `Ctrl+G X` can preserve INSERT-mode intent.
   - Clear completion, search, arg-hint, and prefix hint state before mutating the pane.

4. Implement the conversion callback on `PromptInputBar`.
   - Sync live widget text into `_stack`.
   - Capture active pane text and current local xprompt names.
   - Push the name modal.
   - On cancel, restore focus and leave everything unchanged.
   - On valid name, parse current frontmatter into `PromptFrontmatter`, add the `XPrompt`, serialize back onto
     `_stack.frontmatter`, refresh/show the frontmatter panel, and replace the active pane with the invocation skeleton.
   - When replacing from NORMAL mode, temporarily allow the text edit or update the stack and rebuild; avoid a no-op
     from `TextArea.read_only`.

5. Update user-visible key help.
   - Add `gX / Ctrl+G X` to `PROMPT_INPUT_SECTION` in `src/sase/ace/tui/modals/help_modal/binding_common.py`.
   - No `default_config.yml` change is expected because this is a prompt-local hardcoded `g` continuation, not an
     `ace.keymaps.app` or leader-mode binding. Re-check this during implementation.

6. Keep the TUI event loop responsive.
   - The action should do only local string parsing/model mutation and UI updates.
   - No disk I/O, subprocesses, or catalog loads should be introduced in the key handler or modal callback.

## Tests

Add/adjust focused tests:

- `tests/ace/tui/widgets/test_prompt_g_prefix_hints.py`
  - Dispatch table routes `"X"` and advertises it in hints.
  - Unknown vim-owned `g` continuations still fall through.

- `tests/ace/tui/widgets/test_prompt_stash_capture.py` or a new prompt-local-xprompt test file
  - `gX` converts the active pane, adds `_name` under shared frontmatter `xprompts:`, and replaces that pane with
    `#_name`.
  - `Ctrl+G X` works from INSERT mode.
  - Multi-pane conversion changes only the active pane and keeps other panes intact.
  - Existing frontmatter fields and existing local xprompts are preserved.
  - Duplicate name, cancel, blank pane, and non-prompt modes leave state unchanged with the expected notification/no-op.
  - Jinja variables become `InputType.TEXT` inputs; known globals are not added.
  - Invalid Jinja syntax does not mutate the pane or frontmatter.
  - Generated invocation with inputs uses named args and snippet tabstops.

- `tests/test_keymaps_display_help.py`
  - Help modal includes `gX / Ctrl+G X`.

Run after implementation:

```bash
just install
pytest tests/ace/tui/widgets/test_prompt_g_prefix_hints.py \
  tests/ace/tui/widgets/test_prompt_stash_capture.py \
  tests/test_keymaps_display_help.py
just check
```
