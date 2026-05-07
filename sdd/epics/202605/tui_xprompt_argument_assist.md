---
create_time: 2026-05-07 00:12:22
status: done
prompt: sdd/prompts/202605/tui_xprompt_argument_assist.md
bead_id: sase-28
tier: epic
---
# Plan: TUI XPrompt Argument Completion And Hints

## Goal

Add `sase ace` prompt-bar support for xprompt argument name/type completion and hints, using the structured xprompt
catalog metadata that was recently added for mobile. The TUI should keep the current `Ctrl+T` completion model, enrich
xprompt name completion with visible inputs and types, and then add argument-position hints/actions for users who accept
or type xprompt references such as `#foo:`, `#!foo:`, and `#foo(arg=`.

The backend xprompt parser and launcher remain authoritative. The TUI should provide editor assistance, syntax
generation, and lightweight cursor-position detection only.

Primary research source: `sdd/research/202605/tui_xprompt_argument_hints.md`.

## Current System

- `Ctrl+T` in `PromptTextArea` calls the file-completion mixin and already dispatches to xprompt completion when the
  token starts with `#`.
- Xprompt completion candidates are built in `src/sase/ace/tui/widgets/xprompt_completion.py` from `get_all_prompts()`,
  using canonical `#`/`#!` insertion helpers.
- Completion UI is rendered by `PromptInputBar.show_file_completions()` into `Static#prompt-completion`.
- Xprompt selection/browser modals already render input args with the right required/optional visual treatment via
  `append_input_args()` in `xprompt_browser_helpers.py`.
- The mobile work already exposes `StructuredCatalogEntry` and `StructuredCatalogInput` through
  `build_structured_xprompts_catalog()`, including `name`, `insertion`, `reference_prefix`, `kind`, `input_signature`,
  `inputs`, and `content_preview`.
- `SnippetExpansionMixin` already supports `$1`, `$2`, and `$0` tabstops. Named-argument skeleton insertion should reuse
  this machinery instead of adding a second tabstop implementation.

## Guardrails

- Do not parse `input_signature`; use structured `inputs`.
- Do not show string defaults unless the structured projection explicitly exposes them. The current projection already
  suppresses string defaults.
- Do not run xprompt expansion from the prompt bar on every keypress.
- Do not reuse `extract_token_around_cursor()` for argument-position detection after `:` because `:` is already a token
  delimiter.
- Account for the shared parser behavior where a bare trailing `#foo:` is usually parsed as `#foo` plus trailing text,
  not as a colon-argument reference.
- Keep automatic detection narrow at first. Avoid triggering on prose shorthand such as `#foo: text`, URLs, `foo#bar:`,
  `#foo+`, or unknown xprompt names.
- Do not hijack `Tab`; snippet expansion and tabstop advancement already own it.
- Avoid existing prompt-bar bindings: `Ctrl+T`, `Ctrl+L`, `Ctrl+Y`, `Ctrl+G`, `Ctrl+D`, `Ctrl+J`, `Ctrl+N`, and `Ctrl+P`
  are already meaningful in nearby states.
- Any new configurable keybinding must be reflected in `src/sase/default_config.yml`.
- Project-local xprompts matter. Reuse the existing VCS-tag project detection precedent from the `#@` selection flow.

## Phase 1: Pure Assist Model And Shared Rendering

Owner: one SASE repo agent.

Build a TUI-facing xprompt assist layer that adapts the structured mobile catalog without changing prompt-widget
behavior yet.

Scope:

- Add a pure module such as `src/sase/ace/tui/widgets/xprompt_arg_assist.py`.
- Define immutable assist models for entries, inputs, and active argument hints. Keep these independent of Textual
  widgets so they can be tested cheaply.
- Implement `build_xprompt_assist_entries(project: str | None = None)` using `build_structured_xprompts_catalog()`.
- Provide helper functions for:
  - visible inputs;
  - required inputs;
  - required-only named-argument snippet skeletons;
  - colon-argument skeletons;
  - formatting input labels from structured inputs.
- Extract or mirror the existing `append_input_args()` styling into a shared renderer that both the modal helpers and
  future inline completion UI can use. The modal should keep the same required-bright / optional-dim appearance.
- Add pure tests for required, optional, defaulted, explicit-null, and all-step-input cases.

Acceptance:

- The assist adapter preserves canonical `insertion`, `reference_prefix`, and `kind`.
- String defaults are not surfaced unless already exposed by the structured projection.
- Entries with only step inputs produce no user-facing input hints.
- Existing xprompt browser/select modal tests still pass with no visual regression.

Verification:

```bash
just install
.venv/bin/pytest tests/test_xprompt_catalog.py tests/ace/tui/modals/test_xprompt_browser_helpers.py
```

## Phase 2: Enriched `Ctrl+T` XPrompt Completion

Owner: one SASE repo agent.

Use the assist layer to enrich the existing `Ctrl+T` xprompt completion list with names, types, requiredness, and
canonical insertion metadata. Keep accept behavior unchanged in this phase.

Scope:

- Update `build_xprompt_completion_candidates()` to use assist entries or carry enough metadata to resolve selected
  entries.
- Extend the completion render path so xprompt rows can show a compact input signature or a selected-row detail area.
- Preserve file completion, file-history completion, shared-prefix insertion, and single-candidate insertion semantics.
- Keep `#!` filtering behavior exactly as it is today.
- Reuse the shared input renderer from Phase 1 rather than introducing a second input-label format.
- Add widget tests under `tests/ace/tui/widgets/` for completion display with:
  - required inputs;
  - optional inputs;
  - no visible inputs;
  - standalone `#!` insertion.

Acceptance:

- `Ctrl+T` on `#foo` still filters by xprompt name and inserts canonical references.
- Completion rows/details show input names and types for user-facing inputs.
- Optional inputs are visually distinct from required inputs.
- Existing file completion tests pass unchanged.

Verification:

```bash
.venv/bin/pytest tests/ace/tui/widgets/test_xprompt_completion.py tests/ace/tui/widgets/test_prompt_file_completion.py
```

## Phase 3: Post-Accept Argument Hint Panel And Syntax Actions

Owner: one SASE repo agent.

After accepting an xprompt completion with required visible inputs, keep an advisory hint panel open and provide
explicit actions for colon and named-argument syntax.

Scope:

- Add prompt-text-area state for the active xprompt argument hint: selected entry, reference range, active input index,
  and trigger mode.
- Add a sibling render method on `PromptInputBar`, for example `show_xprompt_arg_hint(...)`, still using
  `Static#prompt-completion` so layout height behavior remains centralized.
- Clear hint state on submit, cancel, escape/normal-mode transition, external editor launch, completion dismissal, and
  edits outside the active reference span.
- Implement a colon action that rewrites only the accepted reference to `#foo:` / `#!foo:` and places the cursor after
  the colon.
- Implement a named-args action that inserts a required-input skeleton such as `#foo(arg1=$1, arg2=$2)$0`, reusing the
  existing snippet tabstop mechanics.
- Choose non-conflicting action bindings or footer-discoverable controls. If bindings are added, update
  `src/sase/default_config.yml`.
- Keep `Enter` behavior predictable: active completion accepts; otherwise submit. Argument hints should not make `Enter`
  launch something different.

Acceptance:

- Accepting an xprompt with required visible inputs shows a compact hint panel.
- Accepting an xprompt with no required visible inputs does not show the post-accept hint panel.
- Colon action preserves surrounding prompt text and places the cursor after `:`.
- Named action preserves surrounding prompt text, inserts named arguments, places the cursor after the first `=`, and
  lets `Tab` advance through fields using existing snippet tabstops.
- Submit/cancel/escape all clear the advisory hint state.

Verification:

```bash
.venv/bin/pytest tests/ace/tui/widgets/test_xprompt_arg_hints.py tests/ace/tui/widgets/test_prompt_snippet_expansion.py
```

## Phase 4: Typed Cursor Detection And `#@` Selection Parity

Owner: one SASE repo agent.

Show the same hint panel when the user types into a known xprompt argument position, and make modal xprompt selection
feed the same post-accept hint path.

Scope:

- Implement pure cursor detection in `xprompt_arg_assist.py` using `iter_xprompt_references()` plus suffix inspection.
- Support the narrow initial trigger set:
  - `#foo:`
  - `#!foo:`
  - `#ns/foo:`
  - `#ns__foo:`
  - `#foo!!:`
  - `#foo??:`
  - `#foo(`
  - `#foo(arg=`
- Track comma progress for colon positional arguments enough to highlight the next input.
- Skip detection while snippet tabstops are active.
- Do not trigger on unknown names, `#foo+`, URLs, `foo#bar:`, or `#foo: text`.
- Wire prompt edit/cursor refresh to update or clear the advisory hint state without running catalog rebuilds on every
  keystroke.
- Extend the `#@` modal selection path so selecting a required-input xprompt opens the same post-accept hint panel as
  `Ctrl+T` acceptance.
- Derive project context from any leading VCS workflow tag using the existing `extract_vcs_workflow_tag()` /
  `extract_project_from_vcs_tag()` precedent.

Acceptance:

- Direct typing after a trailing colon or opening paren reaches the same hint display as completion acceptance.
- `__` aliases resolve to slash names for lookup.
- HITL suffixes are accepted and do not pollute the catalog lookup name.
- Project-local xprompts can be hinted when a leading VCS tag identifies the project.
- Existing VCS MRU cycling and file-history completion behavior does not regress.

Verification:

```bash
.venv/bin/pytest tests/ace/tui/widgets/test_xprompt_arg_assist.py tests/ace/tui/widgets/test_xprompt_arg_hints.py tests/ace/tui/widgets/test_prompt_file_history_completion.py
```

## Phase 5: Type-Aware Argument Value And Name Completion

Owner: one SASE repo agent.

Extend the advisory layer into completion of argument values and missing named argument names where the type metadata is
strong enough to help without pretending to validate full xprompt semantics.

Scope:

- Add an `xprompt_arg_value` or similarly named completion kind that can coexist with the existing file/xprompt/history
  completion state.
- For `path` inputs, delegate to existing file completion using the current argument value slice as the path token.
- For `bool` inputs, offer `true` and `false`; for a single required bool input, optionally offer the existing `+`
  syntax as a lightweight rewrite action.
- For `int` and `float`, show type hints but do not invent value suggestions.
- For parenthesized syntax, complete missing named argument names based on structured `inputs`.
- Make completion and hint state priority explicit: active candidate completion wins; snippet tabstops continue to own
  `Tab`; advisory hints update after edits.
- Add tests for path, bool, named-argument-name, and no-regression cases.

Acceptance:

- `#foo:` where the active input is `path` can use existing file completion behavior.
- `#foo(enabled=)` offers boolean values when `enabled` is a bool input.
- `#foo(` can complete visible input names without duplicating names already present.
- Named argument completion does not interfere with snippet tabstop advancement.

Verification:

```bash
.venv/bin/pytest tests/ace/tui/widgets/test_xprompt_arg_value_completion.py tests/ace/tui/widgets/test_prompt_file_completion.py
```

## Phase 6: Documentation, Polish, And Full Validation

Owner: one SASE repo agent.

Finish user-facing polish, docs, and whole-repo validation after the functional phases land.

Scope:

- Update `docs/xprompt.md` or the relevant TUI docs with the supported prompt-bar assist behavior.
- Add or update screenshots only if the project already has a normal screenshot workflow for this TUI surface.
- Audit prompt-bar keybinding descriptions and footer text for consistency.
- Run focused tests from prior phases, then full project checks.
- Fix small integration issues found by the full check without broad refactors.

Acceptance:

- Documentation describes `Ctrl+T` xprompt completion, post-accept hints, typed colon/parens hints, and type-aware value
  completion.
- The full check suite passes.
- No phase leaves stale TODOs for required functionality.

Verification:

```bash
just install
just check
```

## Suggested Agent Sequencing

The phases are intentionally sequential. Phase 1 establishes the pure model and rendering helpers; Phase 2 consumes them
in completion; Phase 3 adds hint state/actions; Phase 4 adds typed detection and modal parity; Phase 5 builds on the
same active-argument model for value/name completion; Phase 6 validates and documents the complete experience.

Each implementation agent should begin by reading `sdd/research/202605/tui_xprompt_argument_hints.md`, this plan, and
the short-term memories. Agents should keep edits inside their phase ownership unless they hit an integration blocker,
and every agent that changes Python code should run `just install` before its focused tests in this ephemeral workspace.
