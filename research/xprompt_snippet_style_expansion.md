# Research: Snippet-Style Expansion for XPrompts

## Goal

Enable xprompts to be expandable in the prompt editor the same way `ace.snippets` expand today (Tab-driven inline
expansion), including workflows when expansion is safe.

## Current State (What Exists Today)

- Prompt snippets are a TUI-only feature (`ace.snippets`) expanded by Tab in `PromptTextArea._try_expand_snippet`.
- Snippet trigger matching only considers `A-Za-z0-9_` characters, so names containing `/` are not valid snippet
  triggers.
- `#@` opens `XPromptSelectModal`, which lists both simple xprompts and workflows, but it only inserts a reference name
  (it does not expand content).
- Xprompt expansion itself is runtime/query preprocessing (`process_xprompt_references` + embedded workflow expansion).
- Workflow expansion may execute pre/post steps in normal runtime paths, so editor-time expansion must avoid side
  effects.
- A dry embedded-workflow expansion path already exists (`dry_expand_embedded_workflows`) for spec generation.

## Key Constraints

- Editor expansion must be side-effect free: no bash/python/agent step execution.
- Expansion behavior should match existing xprompt parser rules (`#name`, `#name(args)`, `#name:arg`, `#name+`).
- Workflows without `prompt_part` should not be expanded inline.
- Required inputs with no defaults need a UX path (placeholder insertion or clear refusal message).
- Existing snippet Tabstop behavior (`$1`, `$2`, `$0`) should remain intact.

## Feasible Approaches

### Approach 1: Materialize XPrompts into `ace.snippets` at Runtime

Implement a loader that converts all expandable prompts into snippet templates and merges them into the snippet
registry.

How it would work:

- On app init, call `get_all_prompts()`.
- For each simple xprompt (and optionally embeddable workflow), create a snippet template.
- Required inputs become tabstops (`$1`, `$2`, ...), defaults prefilled.

Pros:

- Minimal changes to existing Tab flow.
- Reuses mature snippet tabstop UX.

Cons:

- Poor fit for xprompt names containing `/` (current snippet trigger scanner cannot match them).
- Loses native `#ref` syntax semantics unless we invent new trigger names.
- Hard to represent colon/plus shorthand and nested expansion behavior faithfully.
- Risks divergence between snippet projection and real xprompt expansion logic.

Feasibility: Medium, but behavior drift risk is high.

### Approach 2: Add Tab Expansion for `#ref` Tokens (Dry Resolver)

Keep snippet engine intact, and add a second Tab path that detects an xprompt/workflow reference under cursor and
expands it via side-effect-free resolution.

How it would work:

- In `PromptTextArea` Tab handling:
  - First keep current snippet expansion priority.
  - If no snippet expanded, detect if cursor is at end of a `#...` ref.
  - Run a dry resolver that:
    - Expands simple xprompts via `process_xprompt_references` (scoped to token/selection).
    - Expands embeddable workflows (`prompt_part`) without pre/post execution (reuse/refactor
      `dry_expand_embedded_workflows`).
- Replace the `#ref` token inline with expanded text.

Pros:

- Preserves existing `#name` authoring model.
- Supports namespaced refs (`foo/bar`) naturally.
- Keeps runtime semantics close to current xprompt implementation.
- Works for embeddable workflows without executing scripts.

Cons:

- Requires robust token boundary detection in editor buffer.
- Missing required args need handling (error, no-op, or guided insertion).
- Needs careful parity tests with real expansion logic.

Feasibility: High.

### Approach 3: Two-Phase “Reference Skeleton Then Expand” UX

Tab on `#name` first inserts argument skeleton with tabstops; second Tab on completed `#name(...)` performs dry
expansion.

How it would work:

- If required inputs are missing, convert `#review` to `#review($1, strict=$2)$0` style template.
- User fills inputs with tabstops.
- A later Tab (or explicit key) runs dry expansion of the now-concrete call.

Pros:

- Great UX for typed inputs.
- Avoids silent failure when required args are missing.

Cons:

- Highest implementation complexity.
- Introduces a new interaction model users must learn.
- Requires new state transitions between snippet/tabstop and xprompt expansion modes.

Feasibility: Medium-high, but heavier than necessary for first iteration.

## Recommendation

Adopt **Approach 2** first, with one pragmatic addition from Approach 3: when a `#ref` cannot dry-expand because
required args are missing, insert a guided call skeleton once (with placeholders) instead of failing silently.

Why this is the best fit:

- It aligns with existing `#xprompt` syntax and parser behavior.
- It supports both simple xprompts and embeddable workflows with minimal semantic drift.
- It avoids execution side effects by design.
- It can be delivered incrementally without rewriting snippet infrastructure.

## Suggested Implementation Shape

1. Add a shared dry expansion API in xprompt layer.

- New helper module (example: `sase/xprompt/dry_expand.py`) with something like:
  - `dry_expand_reference(ref_text: str, *, extra_xprompts=None) -> DryExpandResult`
  - `dry_expand_prompt(prompt: str, *, extra_xprompts=None) -> str`
- Internally reuse existing preprocessing and `dry_expand_embedded_workflows` logic to avoid duplicate parsers.

2. Wire editor Tab flow.

- In `PromptTextArea._on_key` after `_try_expand_snippet()` fails:
  - Attempt `_try_expand_xprompt_ref()`.
  - If successful, replace token and position cursor at expansion end.
  - If unresolved-required-args, insert guided call skeleton and use existing snippet tabstops.

3. Keep current `#@` modal behavior, but add optional “Expand on insert” action later.

- Phase 1: no modal UX change needed.
- Phase 2 (optional): Enter inserts `#name`; Shift+Enter inserts expanded content.

4. Add tests.

- Editor tests in `tests/ace/tui/widgets/`:
  - Expands simple xprompt ref.
  - Expands workflow with `prompt_part` only.
  - Does not expand workflow without `prompt_part`.
  - Missing required args generates skeleton placeholders.
  - Namespaced refs with `/` expand.
- Unit tests for dry expansion helper parity with `sase xprompt expand` for safe cases.

5. Documentation updates.

- `docs/ace.md`: clarify snippet Tab precedence + new Tab expansion for `#refs`.
- `docs/configuration.md`: note distinction between `ace.snippets` and xprompt dry expansion.

## Notes on Risk

- Main risk is divergence between dry editor expansion and runtime expansion rules. Centralizing dry logic in xprompt
  package (instead of duplicating parser logic in TUI) mitigates this.
- Avoid calling full workflow executors from editor code to prevent side effects and performance regressions.

## Bottom Line

This integration is viable today without changing workflow execution semantics. The most robust path is to add **dry,
side-effect-free `#ref` expansion on Tab** in the prompt editor, reusing shared xprompt expansion code, with guided
placeholders when required inputs are missing.
