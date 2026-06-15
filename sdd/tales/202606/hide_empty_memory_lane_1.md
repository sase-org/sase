---
create_time: 2026-06-15 07:05:36
status: done
prompt: sdd/prompts/202606/hide_empty_memory_lane_1.md
---
# Hide Empty MEMORY Lane in Agents Metadata Context

## Goal

Stop rendering the `MEMORY` subsection under `AGENT CONTEXT` on the Agents tab metadata panel when the selected agent or
agent family has no memory-read audit events. The `AGENT CONTEXT` section should still appear when another audited
context lane, such as `SKILLS`, has data.

## Current Behavior

`append_agent_context_section()` in `src/sase/ace/tui/widgets/prompt_panel/_agent_context.py` returns early only when
both `memory_reads` and `skill_uses` are empty. When skills exist without memory reads, it still calls:

```python
append_agent_memory_reads_section(text, events=memory_reads, show_empty=True)
```

That produces `▸ MEMORY · none recorded`, which is the unwanted display. Focused tests currently encode that behavior
in:

- `tests/ace/tui/widgets/test_agent_context.py`
- `tests/ace/tui/widgets/test_prompt_panel_header.py`

The lower-level memory and skill lane renderers also support `show_empty=True`; that can stay available for direct
callers/tests even if the aggregate `AGENT CONTEXT` panel stops using empty placeholders.

## Implementation Plan

1. Update `append_agent_context_section()` to render only lanes that have events.
   - Keep the existing early return when both tuples are empty.
   - Append the `AGENT CONTEXT` heading once.
   - Call `append_agent_memory_reads_section()` only when `memory_reads` is non-empty.
   - Call `append_agent_skills_section()` only when `skill_uses` is non-empty.
   - Insert the blank line between lanes only when both lanes render.

2. Preserve lower-level lane behavior.
   - Leave `append_agent_memory_reads_section(..., show_empty=True)` and
     `append_agent_skills_section(..., show_empty=True)` intact because their direct unit tests cover the optional
     placeholder behavior.
   - Avoid loader changes; this is presentation-only and should not add disk I/O, cache churn, or refresh work on the
     TUI path.

3. Update tests to match the new product behavior.
   - Change the skills-only `AGENT CONTEXT` unit test to assert that `▸ MEMORY` and `none recorded` are absent while
     `▸ SKILLS` remains present.
   - Change the prompt-panel header integration test for skill uses without memory reads the same way.
   - Keep memory-only and no-context tests as guardrails.

4. Verify.
   - Run focused tests:
     `pytest tests/ace/tui/widgets/test_agent_context.py tests/ace/tui/widgets/test_prompt_panel_header.py tests/ace/tui/widgets/test_agent_memory_reads.py tests/ace/tui/widgets/test_agent_skill_uses.py`
   - Because source files will change, run `just install` if needed for the ephemeral workspace, then `just check`
     before reporting completion.

## Risk and Rollback

Risk is low because the change is isolated to Rich `Text` composition after cached context events are already loaded.
The main regression risk is accidental lane spacing drift, covered by the focused unit tests and header integration
test. If this causes unexpected UI preference issues, rollback is a small revert of the `append_agent_context_section()`
conditional rendering change and the associated test expectations.
