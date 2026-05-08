---
create_time: 2026-05-08 17:56:29
status: done
prompt: sdd/prompts/202605/xprompt_snippet_composition.md
---
# Plan: XPrompt Snippet Composition

## Goal

Support composing ACE prompt-input snippets that are sourced from xprompts. When an xprompt marked with `snippet: true`
contains a normal xprompt reference such as `#baz`, expanding the trigger word with `Tab` should insert the fully
composed text instead of leaving the nested reference in the prompt input.

Example:

```yaml
xprompts:
  baz:
    snippet: true
    content: "Don't forget to review bazbuz first!"
  foo:
    snippet: true
    content: "Can you help me foobar? #baz"
```

Typing `foo<Tab>` in ACE should expand to:

```text
Can you help me foobar? Don't forget to review bazbuz first!
```

## Current State

- ACE prompt snippet expansion is handled by `PromptTextArea` via `SnippetExpansionMixin`.
- The snippet registry is loaded lazily through `AceApp.get_snippets()`.
- Xprompts with `snippet` set are converted into ACE snippet templates by `src/sase/xprompt/snippet_bridge.py`.
- `_xprompt_to_snippet_template()` currently converts an xprompt's direct content into a snippet template:
  - simple `{{ input }}` references become `$1`, `$2`, etc.
  - legacy `{N}` placeholders become snippet tabstops
  - complex Jinja2 control/comment syntax is skipped
- Normal prompt submission already supports recursive `#xprompt` expansion through `src/sase/xprompt/processor.py`, but
  snippet expansion happens earlier, inside the prompt widget, and currently does not compose nested `#...` references.

## Design

Add snippet composition in the xprompt-to-snippet bridge, not in the text area widget.

The widget should remain a generic snippet-template expander. The bridge is the right layer because it already knows
which xprompts are snippet-backed, has access to xprompt metadata, and is responsible for converting xprompt semantics
into the ACE snippet-template format.

### Expansion Semantics

For each xprompt with `snippet` set:

- Resolve its snippet trigger as today:
  - `snippet: true` uses the basename after the last `/`
  - `snippet: "custom"` uses the custom trigger
  - invalid trigger words are skipped
- Compose nested xprompt references in its content before converting to an ACE snippet template.
- Only normal xprompt references in content are composed (`#name`, `#name(args)`, `#name:arg`, `#name+`, namespaces, and
  `__` slash aliases) using the same behavior as regular prompt expansion.
- Preserve existing snippet-template conversion behavior for the final composed content.
- Keep `ace.snippets` precedence unchanged: user snippets still override xprompt-derived snippets in
  `AceApp.get_snippets()`.

### Reuse Existing Processor Behavior

Prefer reusing the xprompt processor rather than creating a second parser in `snippet_bridge.py`.

Implementation approach:

1. Add a processor entry point that can expand references against a provided xprompt catalog.
   - Current `process_xprompt_references()` always calls `get_all_xprompts()`.
   - Introduce a private helper such as `_process_xprompt_references_with_catalog(prompt, xprompts, ...)` or add an
     optional keyword-only catalog parameter while preserving the public function's current behavior.
   - Keep alias resolution, fenced-block protection, disabled-region protection, shorthand preprocessing, argument
     parsing, recursive expansion, and circular-reference protection on the same path as normal xprompt expansion.
2. In `get_xprompt_snippets(project=None)`, load xprompts once and compose each snippet candidate using that same loaded
   catalog.
   - This avoids re-walking xprompt sources once per snippet.
   - Pass through the `project` argument consistently.
3. Convert the composed content with `_xprompt_to_snippet_template()`.
   - This keeps tabstop handling localized to the existing conversion helper.

## Edge Cases

- Circular references should fail the same way normal prompt expansion fails, using the existing max-depth and
  diagnostic behavior.
- Unknown nested references should remain unchanged, matching normal xprompt expansion behavior.
- References inside fenced code blocks and disabled xprompt regions should remain protected, matching normal expansion.
- Nested references with arguments should work because the processor already supports colon, parentheses, plus,
  shorthand, command substitution, and typed input validation.
- If composition produces complex Jinja2 syntax that `_xprompt_to_snippet_template()` cannot safely convert, the snippet
  should be skipped as it is today for direct complex content.
- Required inputs from the outer snippet should still become snippet tabstops. If a nested xprompt has required inputs,
  it must be referenced with arguments to compose successfully; otherwise the existing xprompt validation path should
  report the same error as regular expansion.
- Nested snippet markers should not matter. Composition should work for referenced xprompts regardless of whether the
  referenced xprompt itself has `snippet: true`, because this is xprompt composition, not snippet-registry lookup.

## Tests

Add focused tests around `src/sase/xprompt/snippet_bridge.py` and existing processor behavior:

- `get_xprompt_snippets()` composes a `snippet: true` xprompt containing `#baz`.
- Referenced xprompt does not need `snippet: true`.
- Nested composition works across multiple levels.
- Unknown nested references are left intact in the produced template.
- Existing conversion tests for Jinja2 inputs, legacy placeholders, defaults, invalid complex Jinja2, and tabstop
  numbering still pass.
- Optional: a prompt-widget integration test can assert that a composed template from the app snippet registry expands
  to the expected inserted text, but most behavior should be tested at the bridge layer to avoid UI coupling.

## Documentation

Update `docs/xprompt.md` in the `Snippet Field` section to mention that xprompt-derived snippets compose normal xprompt
references before becoming ACE snippets.

If the behavior affects user-facing ACE snippet docs, add one sentence to `docs/ace.md` clarifying that this applies to
xprompt-derived snippets, while `ace.snippets` entries remain literal templates.

## Verification

Run targeted tests first:

```bash
just install
pytest tests/test_xprompt_snippet_bridge.py tests/test_snippet_references.py tests/ace/tui/widgets/test_prompt_snippet_expansion.py
```

Then run the repository check before finishing implementation:

```bash
just check
```

## Implementation Order

1. Refactor `processor.py` so the expansion loop can use a supplied catalog without changing public behavior.
2. Update `snippet_bridge.py` to compose snippet xprompt content through the catalog-aware expansion path before
   converting to snippet templates.
3. Add bridge tests for composition, non-snippet referenced xprompts, multi-level composition, and unknown references.
4. Update docs.
5. Run targeted tests, then `just check`.
