---
create_time: 2026-05-31 11:16:03
status: done
prompt: sdd/prompts/202605/full_memory_read_reasons.md
---
# Show Full Memory Read Reasons in ACE Agent Metadata

## Goal

The Agents tab metadata panel already shows a `MEMORY READS` section for audited `sase memory read` calls. Each entry
currently renders the read path and a shortened preview of the read reason. Change that section so the reason shown is
the full `--reason` option argument recorded in the memory-read audit event, without changing the CLI, audit log schema,
event matching, or the number of memory reads shown.

## Current State

- `sase memory read <path> --reason <text>` stores the full reason in `MemoryReadEvent.reason`.
- `src/sase/ace/tui/memory_reads.py` loads matching events for the selected agent and returns the full event objects.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_memory_reads.py` is the only place that shortens reasons for the TUI. It
  currently has `REASON_LIMIT = 88` and calls `_truncate(event.reason, REASON_LIMIT)`.
- Existing renderer tests intentionally assert truncation with an ellipsis, so tests must be updated to lock the new
  behavior.

This means the implementation is presentation-only. No Rust core, CLI parser, JSONL storage, or loader behavior needs to
change.

## Product Decision

Render the full reason inline in the existing `MEMORY READS` entry.

Keep these existing bounds:

- Keep `MAX_VISIBLE_READS = 5`, plus the `+ N more` footer, so a chatty agent cannot fill the metadata header with an
  unbounded event list.
- Keep `PATH_LIMIT = 64`, because the request is specifically about the human-authored reason, and long canonical paths
  are less important than the reason trail.
- Keep whitespace normalized for display, matching the current renderer's behavior, so multiline or oddly spaced shell
  arguments do not break the compact section layout.

Remove this bound:

- Stop limiting the reason text to 88 characters. The user should see the complete rationale that was passed to
  `--reason`.

## Rendering Approach

Replace reason truncation with wrapped full-reason rendering:

- Introduce a display helper that normalizes whitespace but does not drop content.
- Replace `REASON_LIMIT` with a name that reflects layout, such as `REASON_WRAP_WIDTH`.
- Wrap the full reason into one or more visual lines with a hanging indent under the existing `↳` prefix.
- Continue styling the whole reason with `_COLOR_REASON`.
- Do not add a disclosure control, modal, or secondary panel; the existing prompt-panel scroll area already handles
  taller metadata.

The resulting shape should remain compact and readable:

```text
MEMORY READS
1 reads · 1 files · last 14:22:08

  14:22:08  long/generated_skills.md
            ↳ needed generated skill contract context before changing the skill sync
              pipeline, including CLI/runtime parity details that would previously
              have been hidden behind an ellipsis
```

## Implementation Plan

1. Update `src/sase/ace/tui/widgets/prompt_panel/_agent_memory_reads.py`.
   - Keep `_truncate()` for paths or rename it to make clear it is path-only.
   - Remove reason truncation.
   - Add a full-reason append helper using `textwrap.wrap()` with continuation indentation.
   - Preserve existing colors, timestamp formatting, frontmatter marker, summary line, and overflow footer.

2. Update `tests/ace/tui/widgets/test_agent_memory_reads.py`.
   - Replace the ellipsis/truncation test with a test proving a long reason appears in full.
   - Assert no ellipsis is introduced for long reasons.
   - Add or adjust coverage for wrapped continuation lines so future changes do not regress readability.
   - Update imports from `REASON_LIMIT` to the new wrap-width constant if the test needs it.

3. Update `tests/ace/tui/widgets/test_prompt_panel_header.py` only if needed.
   - The current integration test already proves the section is wired into the metadata header.
   - Add a long-reason assertion there only if the unit renderer test is not sufficient after the implementation.

4. Leave `src/sase/ace/tui/memory_reads.py`, `src/sase/memory/read_log.py`, and parser/CLI code untouched.
   - The loader and audit model already preserve full reasons.
   - Changing storage would add risk without helping the requested UI behavior.

## Verification

Run the focused tests first:

```bash
pytest tests/ace/tui/widgets/test_agent_memory_reads.py tests/ace/tui/widgets/test_prompt_panel_header.py
```

Because this repo requires the full check after source changes, then run:

```bash
just install
just check
```

If a visual snapshot unexpectedly changes, inspect the generated artifacts before deciding whether a snapshot update is
warranted. This change should usually be covered by renderer assertions rather than requiring a new PNG golden, because
the existing visual fixture does not appear to exercise memory reads.

## Risks

- Very long reasons make the metadata header taller. That is acceptable because the prompt panel is scrollable, and the
  event count remains capped.
- A single huge unbroken token can still be visually awkward. Wrapping with long-word breaking keeps all content visible
  instead of relying on truncation.
- If a user intentionally passes newlines in `--reason`, display whitespace normalization will flatten them. That
  preserves the full words while keeping the metadata panel stable.
