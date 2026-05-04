---
create_time: 2026-05-04 15:24:50
status: done
prompt: sdd/prompts/202605/require_bang_for_multi_agent_xprompts.md
---
# Require `#!` for multi-agent Markdown xprompts

## Problem

SASE currently has two kinds of prompt definitions that cannot be safely embedded in a larger prompt:

- YAML workflows with no `prompt_part`, which already use explicit standalone syntax via `#!name`.
- Markdown xprompts whose body contains top-level `---` separators, which expand into multiple agent prompts at dispatch
  time.

The second class is currently launched from a sole `#name` segment by
`sase.agent.multi_agent_xprompt.expand_multi_agent_xprompts()`. That is inconsistent with standalone workflow syntax and
hides an important constraint: these xprompts cannot be mixed with surrounding prompt text or embedded inside other
xprompt bodies because expansion must happen before normal prompt preprocessing and before default VCS context is
injected.

The goal is to make multi-agent Markdown xprompts require `#!name`, while preserving normal `#name` behavior for
ordinary embeddable xprompts.

## Current Behavior

Relevant code paths:

- `src/sase/agent/multi_agent_xprompt.py`
  - Detects Markdown multi-agent xprompts by scanning `XPrompt.content` for a `---` line outside fenced code blocks.
  - Parses a sole top-level reference with a local regex that only accepts `#name`, not `#!name`.
  - Expands sole `#multi` segments into multiple prompt segments.
  - Raises `MultiAgentXPromptUsageError` when a multi-agent xprompt appears mid-segment with surrounding prose.
- Dispatch sites already call `expand_multi_agent_xprompts()` before default VCS normalization:
  - `src/sase/agent/launcher.py`
  - `src/sase/main/query_handler/_query.py`
  - `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`
- General reference parsing already understands both `#` and `#!` via `src/sase/xprompt/_parsing_references.py`.
- Display/completion helpers use `Workflow.prompt_kind()`:
  - pure YAML standalone workflows insert `#!name`;
  - converted Markdown xprompts always look like simple `#name` xprompts today, even if their body is multi-agent.

## Desired Semantics

1. A Markdown xprompt whose body contains a top-level `---` separator is a standalone multi-agent xprompt.
2. It must be invoked as a sole segment using `#!name`, with the same argument forms currently accepted for `#name`.
3. A sole `#name` reference to such an xprompt should fail early with a clear message like:
   `Multi-agent xprompt '#name' must be invoked as '#!name' because it expands to multiple agent prompts.`
4. A `#!name` reference to an ordinary embeddable xprompt should remain invalid, matching the existing “Only standalone
   workflows use '#!'” rule.
5. References inside fenced code blocks should not trigger errors.
6. Local frontmatter xprompts should follow the same rule as global xprompts.
7. Recursive multi-agent expansion should use `#!inner` for nested fan-out. Existing inline `#inner` inside an expanded
   segment should fail only when it is a sole or otherwise real reference to a multi-agent xprompt, not when it appears
   inside a fenced example.

## Implementation Plan

1. Add a shared classifier for multi-agent xprompt content.
   - Keep the existing fence-aware `---` detection logic, but expose it through a name that can be reused outside
     dispatch, such as `xprompt_content_has_segment_separators(content: str)`.
   - Keep `xprompt_has_segment_separators(xp: XPrompt)` as a small wrapper for existing callers/tests.
   - Avoid importing `sase.agent.multi_agent_xprompt` from low-level model code if it creates dependency direction
     problems; a small utility module under `sase.xprompt` may be cleaner if display code needs it.

2. Replace the custom top-level-reference regex in `multi_agent_xprompt.py` with the shared lexical parser.
   - Use `iter_xprompt_references()` so both `#name` and `#!name` are parsed consistently.
   - Continue allowing leading prompt directives before the reference.
   - Preserve existing argument behavior by using `XPromptReference.parse_arguments()`.
   - Return marker information in `_XPromptCall`, not just the name and args.

3. Enforce marker semantics in `expand_multi_agent_xprompts()`.
   - If a sole top-level reference resolves to a multi-agent xprompt and uses `#!`, expand it.
   - If it uses `#`, raise `MultiAgentXPromptUsageError` with a targeted “use `#!name`” message.
   - If a segment contains a multi-agent xprompt reference anywhere but is not a sole top-level `#!` reference, raise
     the existing usage error, updated to mention `#!`.
   - If a segment contains `#!ordinary_xprompt`, raise a targeted error equivalent to existing standalone workflow
     validation, rather than passing it through to later inline expansion.

4. Update user-facing reference insertion and completion.
   - Teach `workflow_reference_prefix()` / `workflow_reference_insertion()` that converted simple xprompts with
     multi-agent separators use `#!`.
   - Teach `workflow_kind_value()` or add a distinct kind if useful. The lowest-risk option is to return
     `standalone_workflow` for insertion semantics while keeping display type as `xprompt` where current UI expects
     Markdown xprompts to be xprompts.
   - Update completion filtering so typing `#!` includes YAML standalone workflows and multi-agent Markdown xprompts,
     but excludes ordinary simple/embeddable xprompts.
   - Consider catalog/browser labels so multi-agent Markdown xprompts visually show the `#!` prefix.

5. Update tests around dispatch behavior.
   - `tests/test_multi_agent_xprompt.py` should cover:
     - `#!three` expands into multiple segments.
     - `#three` raises with “use `#!three`”.
     - `#!three(args)` preserves positional/named args.
     - leading directives before `#!three` still attach to the first expanded sub-segment.
     - local frontmatter xprompts require `#!_local_three`.
     - recursive fan-out uses `#!inner`.
     - fenced examples containing `#three` or `#!three` are ignored.
     - `#!single` against a non-multi-agent xprompt is invalid.
   - Existing tests that intentionally call multi-agent xprompts with `#` should be updated to `#!`, except tests
     explicitly covering the new failure.

6. Update tests around reference display/completion/list output.
   - Add a synthetic simple workflow whose prompt_part contains `a\n---\nb`.
   - Assert `workflow_reference_insertion()` returns `#!name`.
   - Assert `sase xprompt list` reports the `#!` insertion/prefix for that entry.
   - Assert prompt completion returns the multi-agent xprompt when completing `#!m`.

7. Run focused verification first, then full repo check.
   - Focused tests:
     - `pytest tests/test_multi_agent_xprompt.py`
     - `pytest tests/ace/tui/widgets/test_xprompt_completion.py tests/main/test_xprompt_handler.py`
   - Repo requirement after file changes:
     - `just install`
     - `just check`

## Risks and Decisions

- Treating multi-agent Markdown xprompts as `standalone_workflow` in display helpers may blur the distinction between
  YAML workflows and Markdown fan-out templates. If that causes UI or JSON compatibility issues, add a new stable kind
  such as `multi_agent_xprompt` while still using `#!` for insertion.
- The dispatch sites currently infer “multi-agent expansion happened” via
  `len(expanded_segments) > len(original_segments)`. That works for normal multi-segment bodies, but an xprompt with
  separators that render down to one non-empty segment should still be considered standalone-only. The marker
  enforcement must happen before that length comparison, so `#multi` errors even if rendering drops all but one segment.
- Recursive expansion currently disables strict mixed-reference checks after the first expansion. The new `#` versus
  `#!` requirement should still be enforced recursively for sole references, while preserving the intent that inline
  references inside an expanded body are left for later normal xprompt expansion when they are ordinary xprompts.
