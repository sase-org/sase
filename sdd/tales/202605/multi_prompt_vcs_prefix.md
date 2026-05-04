---
create_time: 2026-05-04 16:29:59
status: done
prompt: sdd/prompts/202605/multi_prompt_vcs_prefix.md
---
# Plan: Preserve VCS Prefixes For Multi-Agent Markdown XPrompts

## Problem

SASE now treats Markdown xprompts whose content contains top-level `---` separators as standalone multi-agent xprompt
workflows. They must be invoked with `#!name`, and dispatch expands the Markdown body into one prompt segment per
spawned agent.

The current expansion path does not handle a VCS workflow prefix embedded in the calling prompt, for example:

```text
#gh:sase #!some_split_workflow
```

The VCS prefix is launch context, not surrounding prose. It should not make the multi-agent xprompt call invalid, and it
must not apply only to the first generated child prompt. If a caller provides a VCS xprompt workflow prefix such as
`#gh:sase`, `#git:branch`, `#hg:change`, or `#cd:~/repo`, every segment expanded from the Markdown multi-prompt xprompt
should receive that same prefix unless the generated segment already provides its own VCS workflow prefix.

This matters because the multi-prompt launcher resolves VCS metadata per segment. If the prefix is missing from later
generated segments, those agents can launch from home/default context, miss project-local xprompts, or resolve
history/workspace metadata inconsistently.

## Current Flow

Relevant code paths:

- `src/sase/agent/multi_agent_xprompt.py`
  - `expand_multi_agent_xprompts()` detects a sole `#!name` reference to a Markdown xprompt with segment separators and
    expands it into child segments.
  - `extract_top_level_xprompt_reference()` currently accepts leading `%` directives, but not leading VCS workflow tags.
  - Any real multi-agent xprompt reference that is not the sole non-directive content raises
    `MultiAgentXPromptUsageError`.

- `src/sase/agent/multi_prompt_launcher.py`
  - Resolves VCS context per spawned segment using `_extract_vcs_ref()` and `_resolve_segment_vcs_context()`.
  - Already supports mixed VCS refs across manually written multi-prompt segments.

- Dispatch sites:
  - `src/sase/agent/launcher.py`
  - `src/sase/main/query_handler/_query.py`
  - `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`

These sites intentionally expand multi-agent xprompts before default `#cd:~` injection, so the fix should live at the
multi-agent xprompt expansion boundary rather than after launch has already split the generated prompts.

## Desired Behavior

1. A call-site segment with only leading directives, one optional leading VCS workflow prefix, and one standalone
   multi-agent Markdown xprompt reference is valid.

   Example:

   ```text
   %approve
   #gh:sase #!split_work
   ```

2. The call-site VCS prefix is prepended to every generated sub-segment.

   Example body:

   ```text
   Plan
   ---
   Implement
   ---
   Verify
   ```

   Expanded result:

   ```text
   %approve
   #gh:sase Plan
   ---
   #gh:sase Implement
   ---
   #gh:sase Verify
   ```

   Existing behavior where leading directives attach only to the first generated segment should remain unchanged unless
   the directive itself is part of the generated xprompt body.

3. If a generated sub-segment already contains its own VCS workflow prefix, do not prepend the call-site prefix to that
   sub-segment. Segment-local VCS should override inherited call-site VCS.

4. A call-site with surrounding ordinary prose remains invalid.

   ```text
   #gh:sase please run #!split_work
   ```

   This still mixes standalone expansion with prose and should continue to fail.

5. A call-site with multiple VCS workflow prefixes should remain invalid or be treated conservatively as mixed content.
   The feature only needs to support the common unambiguous case: one VCS prefix plus one multi-agent Markdown xprompt
   reference.

6. Fenced code blocks and disabled regions remain protected when detecting references.

## Design

Extend the parsed multi-agent xprompt call model in `multi_agent_xprompt.py` so it can carry an optional
`leading_vcs_ref_text` alongside existing `leading_directives`.

Implementation shape:

1. Add a small helper that recognizes and removes exactly one leading VCS workflow tag from the non-directive body.
   - Use `sase.workspace_provider.get_ref_patterns()` so plugin-provided VCS workflows are handled uniformly.
   - Also honor known-project fallback tags if the existing generic known-project parser is needed for `#gh:sase`-style
     prefixes when a plugin pattern is not installed.
   - Return `(vcs_prefix_text, remaining_body)` only when the VCS tag starts at the beginning of the post-directive body
     and the remainder is non-empty.
   - Preserve the exact matched tag text, stripped of surrounding whitespace, so output prompt history and raw xprompt
     content remain familiar to users.

2. Update `extract_top_level_xprompt_reference()`:
   - Split leading directives as today.
   - Try parsing the remaining body as the sole xprompt reference as today.
   - If that fails, strip one leading VCS workflow tag and retry the sole-reference parse on the remainder.
   - Accept the call only when the remainder is exactly one known xprompt reference and the reference uses `#!` for
     multi-agent Markdown xprompts.
   - Store the VCS prefix text on `_XPromptCall`.

3. Update expansion:
   - After substituting and splitting the xprompt body, prepend the captured VCS prefix to every generated sub-segment
     that does not already contain a VCS workflow reference.
   - Reuse the existing segment-level VCS detection helpers where possible, or add a local helper that delegates to the
     same pattern sources. Avoid duplicating provider-specific regexes.
   - Apply VCS prefixing before recursive expansion so nested multi-agent xprompts inherit the call-site VCS context
     unless they explicitly choose another VCS prefix.
   - Keep existing leading directive behavior: call-site directives attach to the first generated segment only.

4. Keep strict validation:
   - `#gh:sase #split_work` should still raise the “must use `#!`” error for multi-agent Markdown xprompts.
   - `#gh:sase text #!split_work` should still raise the mixed-reference error.
   - `#!ordinary_xprompt` should still raise the invalid `#!` error.

## Tests

Add focused tests in `tests/test_multi_agent_xprompt.py`:

1. `#gh:sase #!three` expands to every generated segment prefixed with `#gh:sase`.
2. `%name:custom\n#gh:sase #!three` preserves `%name` only on the first generated segment and prefixes all generated
   segments with `#gh:sase`.
3. Generated segments that already contain a VCS prefix are not double-prefixed.
4. `#gh:sase #three` raises the existing “must be invoked as `#!three`” error.
5. `#gh:sase please #!three` remains invalid mixed usage.
6. A fenced example containing `#gh:sase #!three` remains ignored.

Add launcher-level coverage if the unit tests do not fully exercise dispatch metadata:

1. Expand a local multi-agent xprompt with a VCS prefix, launch through `launch_multi_prompt_agents()`, and assert every
   spawned child prompt includes the prefix and resolves the same `vcs_ref`.
2. Verify segment-local VCS override still wins for a generated segment that declares its own VCS prefix.

Run targeted tests first:

```bash
.venv/bin/pytest -q tests/test_multi_agent_xprompt.py tests/test_multi_prompt_launcher_wait_vcs.py tests/test_cd_launch_resolution.py
```

Then run the repo-required check after implementation:

```bash
just install
just check
```

## Risks

- VCS workflow tags are plugin-defined, so the detection helper must use existing provider metadata rather than
  hard-coding `gh`, `git`, `hg`, or `cd`.
- Some VCS tag regexes may match too much when followed by another `#!` reference. Tests should cover colon and
  parenthesized forms where feasible.
- Recursive expansion order matters. Prefixing too late can leave nested expanded segments without VCS context;
  prefixing too early can incorrectly reject nested standalone multi-agent references. The safest approach is to prepend
  the inherited prefix to split sub-segments before the existing recursive `expand_multi_agent_xprompts()` call.

## Acceptance Criteria

- `#vcs:ref #!multi_md` is accepted as an unambiguous standalone multi-agent Markdown xprompt invocation.
- Every child prompt produced from that Markdown xprompt includes the caller’s VCS prefix unless that child prompt has
  its own VCS prefix.
- Existing `#!` enforcement for multi-agent Markdown xprompts remains intact.
- Existing per-segment VCS resolution in `launch_multi_prompt_agents()` continues to work without new provider-specific
  branches.
- Focused tests and `just check` pass.
