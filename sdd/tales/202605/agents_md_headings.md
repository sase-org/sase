---
create_time: 2026-05-31 07:59:16
status: done
prompt: sdd/prompts/202605/agents_md_headings.md
---
# Plan: Update AMD-Generated AGENTS.md Memory Section Headings

## Context

`sase amd init` renders managed `AGENTS.md` files through `src/sase/amd/_memory.py`. The current generated memory
headings are tier-numbered:

- `## Tier 1 (short-term) Memory`
- `## Tier 2 (dynamic) Memory`
- `## Tier 3 (long-term) Memory`

The long-term section also contains a redundant nested heading:

- `#### Long-Term Memory Files`

The requested output should use these H2 titles instead:

- `## Short-Term Memory Files`
- `## Dynamic Memory Files`
- `## Long-Term Memory Files`

The long-term file list should live directly under the `Long-Term Memory Files` H2, with no duplicate H4 heading.

## Implementation Approach

1. Update `render_managed_agents()` in `src/sase/amd/_memory.py` to emit the new H2 headings.
2. Remove the redundant `#### Long-Term Memory Files` line from the generated long-term section.
3. Adjust nearby generated prose that refers to tier-numbered sections so it does not point readers at a now-missing
   "tier 3" heading. Keep the behavioral instructions unchanged: short memory is always loaded, dynamic memory is
   prompt-triggered, and canonical long-memory files must still be read via `/sase_memory_read`.
4. Update focused tests in `tests/main/test_amd_init.py` and `tests/main/test_init_memory_handler.py` so they assert the
   new dynamic-memory heading and guard against the removed H4 heading.
5. Run focused tests for AMD/memory init rendering, then run the required repo check sequence for file changes:
   `just install` followed by `just check`.
6. Run `sase amd init` in this workspace after implementation so the checked-in/generated `AGENTS.md` is refreshed with
   the new headings.

## Validation

- `pytest tests/main/test_amd_init.py tests/main/test_init_memory_handler.py`
- `just install`
- `just check`
- `sase amd init`

## Risk

The change is low risk because it is limited to generated markdown text and test expectations. The main compatibility
risk is hidden tests that assert old headings; updating visible tests and adding checks for the removed H4 should make
the intended output explicit.
