---
create_time: 2026-06-22 07:56:26
status: done
prompt: sdd/prompts/202606/expand_xprompt_with_inputs.md
---
# Plan: Expand XPrompts With Inputs via `Ctrl+I` (Stage Inputs in the Property Panel)

## Problem

The `Ctrl+I` ("Expand") keymap on the **Select XPrompt** panel (`#@` selector) inline-expands the highlighted xprompt
into the originating prompt pane. Today it **refuses** any xprompt that declares a required input, surfacing:

> Cannot inline-expand #NAME because input 'foo' is required.

This rejection lives in `expand_inline_xprompt` (`src/sase/ace/tui/widgets/xprompt_inline_expansion.py:115-122`),
because an inline expansion passes no arguments and the Jinja environment uses `StrictUndefined`, so an unfilled
`{{ foo }}` would raise.

The user's goal: **we should be able to expand ANY xprompt markdown file**, including ones with inputs. We now have the
infrastructure to support this:

- the **xprompt property panel** (`FrontmatterPanel`) can hold `input:` declarations on the prompt being authored, and
- the launch path already collects those declared inputs (`InputCollectionModal`) and substitutes them
  (`render_prompt_with_inputs`) before launch.

A markdown (`.md`) xprompt is always a simple prompt-part (`WorkflowKind.SIMPLE_XPROMPT`) — never a
standalone/embeddable `.yml` workflow. So "expand any markdown xprompt" reduces to: **stop rejecting simple xprompts
that declare inputs; instead expand the body with the input placeholders preserved and stage the input declarations in
the property panel, so the user fills them at launch.**

## Design Overview

When `Ctrl+I` expands a simple xprompt that declares inputs:

1. **Render the body with the declared input placeholders preserved.** Local helper references (`#_helper`) and nested
   references are still inlined exactly as today, but every declared top-level input renders back to its literal
   `{{ name }}` form instead of being substituted or erroring.
2. **Splice the rendered body** into the originating pane at the `#` trigger (unchanged `expand_xprompt_at_target` path
   — still one undoable `TextArea` edit).
3. **Merge the xprompt's `input:` declarations into the prompt's frontmatter** (the property panel), then auto-show the
   panel (without stealing focus) so the staged inputs are visible.
4. At launch, the existing flow takes over: `parse_prompt_input_request` sees the declared inputs,
   `InputCollectionModal` collects required values, and `render_prompt_with_inputs` substitutes the `{{ name }}`
   placeholders in the body.

### Why placeholders must live in the body, and helpers must be inlined

This is the load-bearing correctness constraint, verified against the launch pipeline:

- `render_prompt_with_inputs` (`src/sase/agent/prompt_inputs.py:133-176`) substitutes `{{ }}` in the **body only**, then
  removes the `input:` key. It runs **before** xprompt-reference expansion, and local-helper expansion at launch
  receives **no** input scope.
- Therefore a top-level input value only reaches the final prompt if its `{{ name }}` placeholder is in the **body**.
- Consequence: we must **inline local helpers** during expansion (so a helper like `reads.md`'s `_article_search_agent`,
  whose content uses `{{ topic }}`, surfaces `{{ topic }}` into the body), and we must **not** merge the xprompt's local
  `xprompts:` into the prompt frontmatter (a merged helper referencing a top-level input would silently break at
  launch). Only the `input:` declarations are merged.

This keeps the result equivalent to authoring a prompt whose body contains the inputs directly — which the launch path
already handles correctly.

### Placeholder-preservation mechanism

`StrictUndefined` means we must give Jinja a value for every referenced input. Use **identity values**: render with
`named_args = { name: "{{ name }}" for each declared input }` so each `{{ name }}` round-trips to its literal form.

- Bypass type validation by rendering through a copy of the xprompt with its `inputs` list cleared
  (`dataclasses.replace(xprompt, inputs=[])`), so `validate_and_convert_args` short-circuits and the identity strings
  pass straight through (this avoids type errors for `int`/`bool`/`path` inputs). Local-helper inputs are untouched.
- Identity values propagate into inlined local helpers via `_scope_for_local_xprompts`
  (`src/sase/xprompt/processor.py:230-241`), so the `reads.md` pattern round-trips too.
- Pass the same identity map as `scope` to the nested-reference pass so any further reference whose content uses a
  declared input also round-trips instead of raising under `StrictUndefined`.

Best-effort note: plain `{{ name }}` round-trips exactly. A declared input consumed through a Jinja filter/conditional
(`{{ name | upper }}`, `{% if name %}`) is uncommon in markdown xprompts and degrades gracefully (it renders the
placeholder-as-string through the filter rather than crashing); this is acceptable for v1 and called out in tests.

### Behavior for optional inputs

For consistency, **all** declared inputs (required and optional) are preserved as `{{ name }}` placeholders and staged
in the panel, rather than the current behavior of silently baking optional defaults into the text. At launch, an
un-overridden optional input still resolves to its declared default via `render_prompt_with_inputs`, so the final result
is unchanged — but the user can now see and override optional inputs too. This is a deliberate, minor behavior change
for the optional-only case.

### What stays rejected (unchanged)

Standalone workflows (`#!name`), embeddable workflows (workflow steps), and workflow `environment` remain rejected with
their existing messages — these are `.yml` workflows, not markdown xprompts, and carry runtime side effects that cannot
be rendered as inline text. Removing only the required-input rejection fully satisfies "expand any markdown xprompt."

### Undo contract

The body splice remains a single undoable `TextArea` edit (prompt NORMAL-mode `u` restores the pre-expansion body
including the literal `#`). The frontmatter merge is prompt-level shared state, not part of the pane's text-undo batch:
after `u`, the staged inputs remain in the property panel and can be removed there. This is the accepted v1 behavior and
will be documented in code comments and tests. (A future enhancement could make the merge undoable in the same gesture.)

## Implementation

### 1. Inline-expansion helper — preserve placeholders, return declared inputs

File: `src/sase/ace/tui/widgets/xprompt_inline_expansion.py`

- Remove the required-input rejection (`_first_required_input` check and its `REQUIRED_INPUT` error path). Retire or
  repurpose the now-unused `_first_required_input` helper and the `InlineExpansionReason.REQUIRED_INPUT` value.
- Keep the standalone/embeddable/`environment` rejections.
- When the xprompt declares inputs, render via the identity-value mechanism above (cleared-`inputs` copy + identity
  `named_args` + identity `scope` on both the first render and the nested-reference pass). When it declares no inputs,
  keep the current no-arg render exactly.
- Extend `InlineExpansionResult` with the declared inputs to stage, e.g. `inputs: list[InputArg]` (empty for the
  no-input case), so the caller can merge them into frontmatter. Keep the `expanded_text`/`error`/`reason` contract.
- Preserve all existing exception handling (`XPromptError`, validation errors, `SystemExit` from legacy expansion).

### 2. Merge staged inputs into the prompt frontmatter / property panel

File: `src/sase/ace/tui/widgets/_prompt_input_bar_frontmatter.py` (with a small `PromptInputBar` surface as needed)

- Add a method (e.g. `merge_frontmatter_inputs(inputs: list[InputArg]) -> None`) that:
  - parses the current `self._stack.frontmatter` via `PromptFrontmatter.parse`,
  - adds each input that is not already declared (existing prompt declarations win on a name collision, so user edits
    are never clobbered),
  - writes back with `set_frontmatter_model`,
  - calls `refresh_frontmatter_panel_from_stack()` so the panel shows the staged inputs without stealing focus from the
    body.
- Reuse the existing `PromptFrontmatter.set_input` mutator; do not hand-roll YAML.

### 3. Wire the expansion callback to splice + merge

File: `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_requests.py` (`on_xprompt_expand`)

- After a successful `expand_inline_xprompt`, splice the body via the existing `expand_xprompt_at_target` (unchanged),
  then, if `result.inputs` is non-empty, call `origin_bar.merge_frontmatter_inputs(result.inputs)`.
- Keep the stale-target guard and error-return contract (modal stays open on error, dismisses on success).

### 4. Hints / help / docs

- Verify the selector footer hint and the `?` help popup still describe `Ctrl+I` accurately now that it also handles
  input-bearing xprompts (per `src/sase/ace/AGENTS.md`: update the help popup when ace behavior changes). No new keymap
  is introduced, so no `default_config.yml` change is expected — confirm.

### Rust core boundary

No `../sase-core` change is required. This reuses existing Python expansion primitives (`processor.py`) and the pure
Python `PromptFrontmatter` parse/serialize model; the only Rust-backed piece (frontmatter validation) is untouched. The
decision/render logic stays pure and unit-testable in `xprompt_inline_expansion.py`, consistent with where the original
feature lives.

## Testing

Unit (`tests/ace/tui/widgets/test_xprompt_inline_expansion.py`):

- Replace `test_required_input_returns_error`: a required input now expands, the body preserves `{{ name }}`, and the
  result returns the input declaration to stage.
- Input used directly in the body → `{{ name }}` preserved; declared inputs returned.
- Input consumed inside a local helper (the `reads.md` pattern) → helper inlined, `{{ name }}` surfaced in the body,
  declared inputs returned.
- Optional inputs preserved as placeholders (not baked).
- Mixed required + optional; multi-input; multi-agent (`---`) body still preserved as text.
- Standalone/embeddable/`environment` still rejected with the existing messages.

Widget/integration:

- `tests/ace/tui/test_prompt_bar_xprompt_selector_requests.py`: `Ctrl+I` on an input-bearing xprompt splices the body
  into the origin pane AND the property panel becomes visible with the staged inputs; other panes untouched; success
  dismisses the modal.
- Frontmatter merge: collision keeps the existing declaration; no stray YAML; panel refreshes.
- Undo: after expansion, NORMAL-mode `u` restores the pre-expansion body text.

End-to-end correctness (the load-bearing check):

- A test that takes the spliced body + merged `input:` frontmatter and runs the launch substitution
  (`render_prompt_with_inputs` with a supplied value) to confirm the final prompt has the value substituted — for both
  the body-direct pattern and the inlined-helper (`reads.md`) pattern.

## Acceptance Criteria

- `Ctrl+I` on a markdown xprompt that declares inputs (required or optional) expands its body into the originating pane
  instead of erroring.
- The xprompt's declared inputs appear in the prompt property panel after expansion (auto-shown, focus stays on body).
- Top-level input placeholders are preserved in the body — directly and via inlined local helpers — and resolve
  correctly at launch through the existing input-collection + substitution flow, for both patterns.
- Existing `Enter` (insert reference) and `Ctrl+E` (open definition) behaviors are unchanged.
- Standalone/embeddable/side-effectful `.yml` workflows still show their existing errors and keep the selector open.
- `Esc` then `u` after a successful expansion restores the pre-expansion body text.
- `just check` passes.
