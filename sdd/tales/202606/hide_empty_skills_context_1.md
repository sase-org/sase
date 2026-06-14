---
create_time: 2026-06-14 13:40:19
status: done
prompt: sdd/prompts/202606/hide_empty_skills_context_1.md
---
# Plan: Hide Empty SKILLS Lane in AGENT CONTEXT

## Context

The Agents tab metadata/header panel builds its AGENT CONTEXT block through `append_agent_context_section` in
`src/sase/ace/tui/widgets/prompt_panel/_agent_context.py`. That composer always passes `show_empty=True` to both lane
renderers:

- `append_agent_memory_reads_section(...)`
- `append_agent_skills_section(...)`

As a result, an agent family with memory reads but no xprompt skill-use log events renders:

```text
▸ SKILLS · none recorded
```

The requested product behavior is narrower: if the family has not used any xprompt skills, the AGENT CONTEXT section
should not include the SKILLS subsection at all.

## Scope

This is presentation-only TUI behavior. It does not require changing the Rust core/backend boundary, the skill-use log
schema, agent family event attribution, or log loading. The loaded short-term memory confirms this belongs in the Python
TUI renderer unless inspection reveals shared backend behavior, which it did not.

## Implementation Approach

1. Update the AGENT CONTEXT composer in `_agent_context.py` so it only appends the SKILLS lane when `skill_uses` is
   non-empty.

2. Preserve the standalone lane helper contract in `_agent_skill_uses.py`: direct callers can still pass
   `show_empty=True` and receive `▸ SKILLS · none recorded`. That keeps the lower-level helper test meaningful and
   avoids turning this into a broader API change.

3. Preserve the existing AGENT CONTEXT section gate: if both `memory_reads` and `skill_uses` are empty, render nothing.

4. Keep the memory lane behavior unchanged unless tests reveal a contradiction: a skills-only context may still render
   `▸ MEMORY · none recorded`. The user request is specifically about omitting the empty SKILLS subsection when no
   xprompt skills were used.

5. Adjust blank-line composition so hiding SKILLS does not leave a dangling empty lane separator after MEMORY in
   memory-only contexts.

## Test Plan

1. Update focused renderer tests in `tests/ace/tui/widgets/test_agent_context.py`:
   - Memory-only context should contain AGENT CONTEXT and MEMORY details.
   - Memory-only context should not contain `▸ SKILLS`.
   - Memory+skills ordering and style tests should continue to validate both lanes when both event types exist.

2. Update the header integration test in `tests/ace/tui/widgets/test_prompt_panel_header.py`:
   - The workflow-variables-before-agent-context case currently covers memory-only context and should assert that
     `▸ SKILLS` is absent.
   - The skills-only test can remain as-is if we preserve empty MEMORY placeholder behavior.

3. Keep `tests/ace/tui/widgets/test_agent_skill_uses.py` unchanged unless an implementation detail forces otherwise,
   because it tests the lower-level renderer's explicit `show_empty=True` behavior.

4. Run targeted tests first:

```bash
pytest tests/ace/tui/widgets/test_agent_context.py tests/ace/tui/widgets/test_prompt_panel_header.py tests/ace/tui/widgets/test_agent_skill_uses.py
```

5. Because implementation changes will modify repo files, run the required repo check before finishing:

```bash
just install
just check
```

If `just check` is too slow or fails for unrelated environment reasons, report the exact failure and the targeted test
result.

## Risks

- Existing tests currently encode the old placeholder behavior, so they must be updated deliberately.
- Visual snapshot coverage appears to use a context with both MEMORY and SKILLS, so this change should not require PNG
  snapshot updates. If a visual test fails because a memory-only fixture exists elsewhere, inspect the diff before
  accepting any snapshot change.
