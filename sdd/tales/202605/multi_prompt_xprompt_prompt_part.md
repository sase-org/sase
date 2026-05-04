---
create_time: 2026-05-04 17:13:47
status: done
prompt: sdd/prompts/202605/multi_prompt_xprompt_prompt_part.md
---
# Plan: Treat Multi-Prompt XPrompts As Embeddable Prompt Parts

## Context

SASE currently detects Markdown xprompts whose body contains top-level `---` separators in
`src/sase/agent/multi_agent_xprompt.py`. Recent work made those xprompts behave like standalone workflows: callers must
use `#!name`, and the reference must be the only non-directive content in the prompt segment. That breaks useful calls
such as:

```text
#!research_swarm:: summarize this feature
```

or:

```text
#gh:sase #research_swarm:: summarize this feature #some_context
```

The desired model is different: a multi-prompt Markdown xprompt still expands into multiple agent prompts, but its first
listed prompt is also its embeddable `prompt_part`. When the call site includes other text or other embeddable xprompts,
that surrounding context belongs in the first generated prompt. A leading VCS xprompt workflow remains launch context
and must be inherited by every generated prompt unless a generated prompt has its own VCS tag.

## Current Behavior To Change

Relevant implementation points:

- `expand_multi_agent_xprompts()` only expands when `extract_top_level_xprompt_reference()` finds a sole top-level
  `#!name` call.
- Any other real reference to a multi-prompt xprompt raises `MultiAgentXPromptUsageError`.
- `expand_single_xprompt()` and `process_xprompt_references()` currently expand the whole Markdown body, including
  `---`, when a multi-prompt xprompt is embedded normally.
- VCS inheritance already exists for sole `#vcs:ref #!name` calls via `leading_vcs_ref_text` and
  `_prepend_inherited_vcs_ref()`.

## Desired Semantics

1. A bare/inline reference to a multi-prompt Markdown xprompt is valid in a larger prompt segment.
2. The xprompt body is rendered with the call-site args, split on top-level `---`, and the first rendered sub-segment
   replaces the xprompt reference in the original segment.
3. The original segment, with the reference replaced by the first rendered sub-segment, becomes the first expanded agent
   prompt.
4. The remaining rendered sub-segments become additional agent prompts after the first.
5. If the original segment has a leading VCS xprompt workflow, prepend that VCS tag to every generated prompt that lacks
   its own VCS tag. For the first prompt, avoid duplicating the tag when it was already present in the original segment.
6. A sole `#name` or `#!name` reference to a multi-prompt xprompt still fans out exactly like a standalone call, so
   recent command forms keep working during the transition.
7. `#!ordinary_xprompt` remains invalid because ordinary embeddable xprompts are not standalone workflows.

## Implementation Approach

1. Add a helper in `multi_agent_xprompt.py` to render a multi-prompt xprompt into split sub-segments:
   - Reuse `expand_single_xprompt()` for argument rendering.
   - Reuse `split_segments_protecting_fences()` for segment splitting.
   - Preserve the existing recursion depth guard.

2. Extend expansion to handle embedded references:
   - Keep the existing top-level path for sole calls, but allow either `#name` or `#!name` for multi-prompt xprompts.
   - Replace the strict “mixed usage” error with an embedded expansion path when a segment contains exactly one real
     multi-prompt xprompt reference.
   - Parse that reference’s args using the existing `XPromptReference` helpers.
   - Replace only the referenced text span with the first rendered sub-segment, preserving surrounding user text and
     other xprompt references for later normal xprompt processing.
   - Append the remaining rendered sub-segments after that first reconstructed segment.

3. Keep validation conservative:
   - If a segment contains multiple multi-prompt xprompt references, raise a clear usage error rather than trying to
     interleave two fan-outs.
   - Continue ignoring references inside fenced blocks and disabled regions.
   - Continue rejecting `#!ordinary_xprompt`.

4. Preserve VCS behavior:
   - Reuse the existing leading VCS stripping/detection helpers.
   - For embedded expansion, detect a leading VCS tag from the original segment and inherit it into generated follow-up
     prompts.
   - Do not prepend inherited VCS to a generated sub-segment that already contains a VCS tag.
   - Do not duplicate the leading VCS tag on the reconstructed first prompt.

5. Prevent normal xprompt expansion from leaking `---` into single-agent prompts:
   - Update `expand_single_xprompt()` or a narrow helper it calls so embeddable expansion of a multi-prompt xprompt uses
     only the first rendered segment when invoked by normal xprompt processing.
   - Ensure the dispatch-time multi-agent expansion path still gets the full rendered body before splitting.

## Tests

Add or update focused tests in `tests/test_multi_agent_xprompt.py`:

- `#three` as a sole segment expands to all sub-prompts.
- `#!three` as a sole segment remains accepted for compatibility.
- `Please #three help` expands into `Please <first segment> help` plus the remaining sub-prompts.
- `#three:: user text` or the parser-equivalent shorthand renders the user text into the first segment and preserves
  later sub-prompts.
- `#gh:sase #three:: user text` keeps `#gh:sase` on the first prompt and prepends it to later prompts.
- A later generated segment with its own VCS tag is not double-prefixed.
- Multiple multi-prompt xprompt references in one segment raise a clear usage error.
- Fenced examples remain ignored.
- `#!single` for an ordinary xprompt still raises.

Add processor-level coverage for the prompt-part rule:

- `process_xprompt_references("before #three after")` expands only the first sub-segment, not the full `---` body.

Run:

```bash
.venv/bin/pytest -q tests/test_multi_agent_xprompt.py tests/test_multi_prompt.py tests/test_xprompt_processor_args.py
just install
just check
```

## Risks

- Shorthand spans such as `#name:: text` must be replaced using the full parsed reference span, not only the lexical
  `#name` prefix.
- Dispatch-time expansion and normal xprompt expansion need slightly different behavior: dispatch needs all segments;
  normal embedded processing needs only the first segment.
- The `#!` compatibility path should not weaken the existing rule for true ordinary xprompts or no-`prompt_part` YAML
  workflows.
