---
create_time: 2026-05-01 15:01:51
status: done
prompt: sdd/prompts/202605/prompt_history_rows.md
---
# Prompt History One-Line Rows

## Context

The `sase ace` prompt history modal currently renders each history option as:

```
<marker> <branch/workspace padded to max seen length> | <prompt preview>
```

This is hard to scan when branch names or prompts are long because the row can wrap inside the `OptionList`, making a
single history entry occupy multiple visual lines. The preview panel already shows full prompt text and metadata, so the
list should optimize for dense selection and comparison instead of full detail.

## Goals

- Make every prompt history entry render as a compact single visual row.
- Add useful compact metadata directly to each row, especially when the prompt was last run.
- Preserve the current interaction model: filtering, cancelled toggle, submit/edit/load/copy actions, and preview panel
  metadata.
- Keep the design readable in narrow terminal widths and attractive in wide terminals.

## Design

Use a fixed, compact row grammar:

```
<mark> <last-used> <context>  <prompt>
```

Where:

- `<mark>` remains the existing visual status/context marker:
  - `*` current branch/CL
  - `~` current workspace/project
  - `x` cancelled
  - blank for everything else
- `<last-used>` is a compact, human-parsable timestamp derived from `entry.last_used`.
  - For valid SASE history timestamps, display `MM-DD HH:MM`.
  - If parsing fails, fall back to the raw timestamp trimmed to the same width.
- `<context>` is the branch/workspace, capped to a modest fixed width and ellipsized from the right.
- `<prompt>` is the first-line prompt text, whitespace-normalized and capped.

Rows should use `rich.text.Text(no_wrap=True, overflow="ellipsis")` so Textual does not wrap individual options. The
content itself should also be pre-truncated so test behavior is deterministic and rows stay visually balanced even
before terminal-level clipping.

## Implementation Plan

1. Add small pure helpers in `prompt_history_modal.py`:
   - Normalize prompt text to one line.
   - Ellipsize text to a fixed width.
   - Format history timestamps from `YYMMDD_HHMMSS` to `MM-DD HH:MM` with fallback.
2. Replace `_PromptDisplayItem.display_branch` with a compact context string or compute it in the row formatter.
3. Rework `_create_styled_label()` to build the new one-line grammar with muted timestamp/context styling and prompt
   text as the strongest signal.
4. Keep the preview panel metadata unchanged so users can still inspect full `Created` and `Last Used` values.
5. Add focused unit tests for the row helper behavior:
   - long branch and long prompt do not produce newline characters and are ellipsized;
   - valid timestamps display compact datetime;
   - invalid timestamps fall back gracefully;
   - cancelled entries are visually marked and dimmed.
6. Run targeted tests for prompt history modal/history behavior, then run `just check` after code changes as required by
   repo instructions.

## Non-Goals

- Do not alter prompt history storage format.
- Do not change sort order or filtering semantics.
- Do not redesign the preview pane in this pass.
- Do not change command or hook history modals unless a shared helper becomes clearly worthwhile.
