---
create_time: 2026-03-26 14:27:33
status: done
prompt: sdd/prompts/202603/prompt_wrap_cursor_restore.md
---

# Fix prompt auto-wrap cursor drift after prettier reflow

## Goal

Diagnose and fix a bug in the prompt input widget where, after auto-wrap / prettier reflow, the cursor can move to the
wrong side of nearby characters (for example, a letter that was before the cursor ends up after it).

## Diagnosis Summary

- Primary suspect: `src/sase/ace/tui/widgets/prompt_text_area.py`, method `_format_with_prettier()`.
- Current cursor restoration algorithm:
  - Computes absolute pre-format offset (`cursor_offset`) from `(row, col)` in original text.
  - Replaces full document with formatted text.
  - Restores cursor to the same absolute offset in the new text.
- Why this fails:
  - Prettier may normalize text before the cursor (collapse spaces, reflow lines, adjust newlines).
  - When character counts before cursor change, same absolute offset no longer refers to the same semantic position.
  - Result: cursor drifts (often one char right/left), making nearby letters appear to “jump” across cursor.

## Implementation Plan

1. Add a regression test that models whitespace normalization before cursor.

- Create a targeted unit test for `PromptTextArea._format_with_prettier()`.
- Mock the prettier subprocess so the test is deterministic (no external prettier dependency).
- Use an input where cursor is between stable neighbors but formatted output shortens text before cursor (e.g.
  double-space collapse).
- Assert cursor remains between equivalent logical neighbors in formatted output.

2. Replace naive absolute-offset restoration with diff-based mapping.

- Add helper in `PromptTextArea` to map old offset into new text using `difflib.SequenceMatcher` opcodes.
- Mapping behavior:
  - `equal`: preserve intra-block relative offset exactly.
  - `delete`: map to deletion start in new text.
  - `replace`: clamp to replacement range in new text.
  - `insert`: does not consume old chars; continue scanning.
- Use mapped offset after prettier replacement, then convert offset to `(row, col)`.

3. Keep existing safety guards unchanged.

- Preserve `_formatting` re-entrancy guard.
- Keep “user typed while prettier running” short-circuit.
- Keep fallback behavior for prettier failures / missing binary.

4. Validate end-to-end for this bug class.

- Run the new targeted test.
- Run existing prompt text area tests most likely to regress (normal-mode/join tests at minimum).
- If environment permits, run broader prompt widget test subset.

## Risks / Considerations

- Diff-based mapping in heavily edited text may not be mathematically perfect for every ambiguous transform.
- However, it is strictly better than absolute offset for whitespace/newline normalization and should directly fix this
  bug class.
- If edge cases remain, future refinement could use token/anchor heuristics around cursor.

## Acceptance Criteria

- Repro test fails on old behavior and passes after fix.
- Cursor position after auto-wrap reflow no longer crosses adjacent characters in the tested case.
- Existing prompt text area tests continue to pass.
