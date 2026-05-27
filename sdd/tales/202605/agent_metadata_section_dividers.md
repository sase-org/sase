---
create_time: 2026-05-27 10:14:20
status: done
prompt: sdd/prompts/202605/agent_metadata_section_dividers.md
---
# Plan: Agent Metadata Section Dividers

## Goal

Improve readability in the `sase ace` Agents tab metadata panel by inserting the same kind of dim horizontal divider
used before sections like `AGENT XPROMPT` when the header transitions from ordinary agent metadata fields into larger
sections.

The requested separators should appear:

- before `MEMORY READS` when that section exists
- before `STEP METADATA` when that section exists

This is a TUI rendering-only change. It should not alter agent scanning, memory-read auditing, artifact discovery,
deltas computation, workflow state parsing, or the data models.

## Current State

`build_header_text()` in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` builds the metadata header. It
appends ordinary fields such as `ChangeSpec`, `Workspace`, `Model`, `DELTAS`, `ARTIFACTS`, and `Timestamps`, then
optionally appends `MEMORY READS`, then optionally appends `STEP METADATA`.

The `AGENT XPROMPT` rendering path already visually separates major sections with a 50-column dim rule:

```text
──────────────────────────────────────────────────
```

`MEMORY READS` currently starts immediately after the previous field section, and `STEP METADATA` currently only gets a
blank line. That makes the boundary between compact metadata fields and larger sections less clear.

## Design

Use the existing visual language: a blank line, a 50-column `─` rule in dim style, and another blank line before the
next section header.

Prefer a small shared helper local to `_agent_display_parts.py` or the prompt-panel helpers so the exact divider shape
does not get hand-copied across the header logic. The helper should append to an existing `rich.text.Text`.

Rendering should stay conditional:

- no `MEMORY READS` divider if there are no memory reads
- no `STEP METADATA` divider if there are no displayable meta fields
- no memory reads on the cheap header path, preserving the existing fast j/k behavior

The order remains unchanged:

1. ordinary metadata fields
2. `DELTAS` / `ARTIFACTS`
3. divider + `MEMORY READS` when present
4. divider + `STEP METADATA` when present
5. error/final header divider behavior as today

## Implementation

1. Add a helper for appending a major-section divider, matching the existing `AGENT XPROMPT` rule style.
2. Before calling `append_agent_memory_reads_section()`, check whether `summary.memory_reads` is non-empty. If so,
   append the divider, then append the memory reads section.
3. Before rendering `STEP METADATA`, check whether `extract_meta_fields()` returned entries. If so, append the divider,
   then render the existing `STEP METADATA` header and fields.
4. Keep the change scoped to header rendering. Do not change `_agent_memory_reads.py` data formatting unless tests
   reveal a spacing issue caused by the new divider.

## Tests

Update focused renderer tests rather than broad UI snapshots first:

- Extend `tests/ace/tui/widgets/test_prompt_panel_header.py` so the integration case with both `MEMORY READS` and
  `STEP METADATA` asserts a dim divider appears before each section and that ordering remains intact.
- Extend or add `tests/ace/tui/widgets/test_agent_display_metadata.py` coverage for `STEP METADATA` so the section
  starts after the divider when meta fields exist and no divider appears when it does not.
- Run the focused tests for prompt-panel header/metadata rendering.
- Because this repo requires it after file changes, run `just install` if needed and then `just check` before finishing.

## Risk

The main risk is visual churn in snapshot tests because the panel gains extra vertical space when these sections exist.
That is intentional for the requested readability improvement. If PNG snapshots fail, inspect the rendered diff and
update snapshots only if the added separators are the sole expected change.
