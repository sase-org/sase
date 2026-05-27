---
create_time: 2026-05-27 11:13:41
status: done
---
# Render Step Metadata Before Memory Reads

## Goal

Always render the `STEP METADATA` section above the `MEMORY READS` section in the Agents tab prompt-panel details header
whenever both sections are present.

This is a presentation-ordering change. It should not alter how metadata fields are extracted, how audited memory reads
are loaded or formatted, or what appears on the cheap header path.

## Current Behavior

The agent details header is built in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`.

`build_header_text()` currently renders sections in this order:

1. `AGENT DETAILS` metadata rows.
2. Expensive full-header enrichments when `cheap=False` and a summary is available:
   - `Deltas:`
   - `Artifacts:`
   - `MEMORY READS`
3. `STEP METADATA`, if displayable `meta_*` fields exist.
4. `ERROR`, if present.
5. The trailing separator before the prompt/reply content.

That means a full header with both audited memory reads and step metadata currently shows `MEMORY READS` before
`STEP METADATA`. The existing regression test in `tests/ace/tui/widgets/test_prompt_panel_header.py` asserts this old
order.

## Target Behavior

For agent detail headers, the intended order should be:

1. `AGENT DETAILS` metadata rows.
2. Full-header deltas and artifacts, when present.
3. `STEP METADATA`, when displayable step metadata exists.
4. `MEMORY READS`, when audited reads exist.
5. `ERROR`, if present.
6. The trailing separator.

The cheap header path should continue to omit expensive memory-read loading and should still render `STEP METADATA` when
the selected agent has displayable step metadata.

## Implementation Plan

1. In `build_header_text()`, compute displayable step metadata once from `agent.step_output` when it is a dict.
   - Keep the existing special-key behavior for `meta_project`, `meta_changespec`, and `meta_workspace`.
   - Keep `extract_meta_fields()` as the source of truth for displayable `STEP METADATA` rows.

2. Move the `STEP METADATA` rendering block so it runs after full-header deltas/artifacts and before the memory-read
   section.
   - Preserve the existing major-section divider immediately before `STEP METADATA`.
   - Preserve the existing section header styling and field styling.
   - Do not make memory reads available on the cheap path.

3. Render `MEMORY READS` after `STEP METADATA`.
   - Keep the existing `if summary.memory_reads:` guard.
   - Keep the existing major-section divider before `MEMORY READS`.
   - Do not change `append_agent_memory_reads_section()` formatting or truncation behavior.

4. Leave unrelated renderers alone.
   - `src/sase/ace/tui/widgets/prompt_panel/_agent_memory_reads.py` is a section formatter and should not need changes.
   - `src/sase/ace/tui/widgets/prompt_panel/_workflow_render.py` has workflow-level `STEP METADATA` but no
     `MEMORY READS` section, so it is out of scope.
   - Historical SDD/research plan files that describe the previous order should not be edited as part of this narrow UI
     behavior change.

## Test Plan

1. Update `tests/ace/tui/widgets/test_prompt_panel_header.py`.
   - Rename or adjust the existing order regression test so it describes the new behavior.
   - Assert that both `STEP METADATA\n` and `MEMORY READS\n` are present.
   - Assert that the dim major-section divider still appears before each section.
   - Assert `plain.index("STEP METADATA\n") < plain.index("MEMORY READS\n")`.

2. Keep existing absence and cheap-path coverage.
   - `test_cheap_header_omits_memory_reads` should continue to prove memory reads are not loaded/rendered on the cheap
     path.
   - `test_no_events_omits_memory_reads_section` should continue to prove empty memory-read state has no placeholder
     section.
   - Existing `TestStepMetadataHeader` tests should continue to prove step metadata appears only when displayable meta
     fields exist.

3. Run focused tests:

   ```bash
   .venv/bin/python -m pytest \
     tests/ace/tui/widgets/test_prompt_panel_header.py \
     tests/ace/tui/widgets/test_agent_display_metadata.py
   ```

4. After source/test changes, run the repository-required check:

   ```bash
   just check
   ```

If the workspace lacks current dependencies, run `just install` before the test commands.

## Risks And Edge Cases

- Agents with memory reads but no displayable step metadata should still show `MEMORY READS` exactly as before, with one
  divider before it.
- Agents with step metadata but no memory reads should still show `STEP METADATA` exactly as before.
- Agents with non-dict `step_output` should not render `STEP METADATA`.
- Special routing metadata should remain promoted into normal header rows and excluded from `STEP METADATA`.
- The change should not introduce disk access into the cheap header path; memory reads must remain summary-driven
  full-header data.
