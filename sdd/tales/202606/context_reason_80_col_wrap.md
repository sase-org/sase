---
create_time: 2026-06-26 08:36:34
status: done
prompt: sdd/prompts/202606/context_reason_80_col_wrap.md
---
# Plan: SASE CONTEXT Reason Wrapping at 80 Columns

## Goal

Make every rendered reason line in the Agents tab metadata panel's `SASE CONTEXT` section fit within a strict 80-column
terminal limit, including leading whitespace, glyphs, role columns, and continuation indentation. Long reasons should
wrap cleanly at word boundaries when possible, without truncating content.

## Current Findings

- The shared rendering path is `src/sase/ace/tui/widgets/prompt_panel/_agent_context_common.py`.
- `append_context_reason()` currently wraps reason payload text with `REASON_WRAP_WIDTH = 88`.
- That width applies only to the text after the `↳ ` prefix. It does not count the leading indentation or glyph prefix.
- For ordinary rows, the rendered prefix is currently 16 cells, so the existing maximum rendered reason line is about
  104 cells.
- For attributed family rows, the role column adds 7 cells, so the existing maximum rendered reason line is about 111
  cells.
- The same helper is used by MEMORY, SKILLS, and WORKSPACES lanes, so fixing the shared helper should cover all reasons
  in the section.
- Existing tests cover long reason wrapping, but they assert only the post-prefix payload width. They do not enforce the
  total rendered line width.

## Proposed Design

1. Replace the payload-width constant with an explicit total line limit.

   Use a constant such as `REASON_LINE_CELL_LIMIT = 80` in `_agent_context_common.py`. Keep any compatibility export
   only if existing imports require it, but make the source of truth the total rendered cell limit rather than a fixed
   reason payload width.

2. Compute the available reason payload width per row.

   In `append_context_reason()`, build the first-line prefix and continuation prefix as it does today, then compute:
   - first line payload width = `80 - rendered_cell_width(prefix)`
   - continuation payload width = `80 - rendered_cell_width(continuation_prefix)`

   This matters because attributed rows have a wider prefix than ordinary rows.

3. Use rendered cell measurement, not Python string length, for the limit.

   Use Rich's cell-width helpers, for example `rich.cells.cell_len`, so the rule matches terminal columns. This keeps
   the implementation aligned with the requirement that total rendered columns matter.

4. Preserve pretty wrapping.

   Add a small helper that wraps normalized reason text by terminal cells:
   - Prefer breaking on whitespace.
   - Do not break on hyphens unless an individual token is too wide.
   - If a single token exceeds the available payload width, split that token by cells as a fallback so the 80-column
     contract is still strict.
   - Preserve the existing behavior where empty reasons render just the `↳` line.

5. Keep the change presentation-only.

   Do not move this logic into `sase-core`; it is specific to TUI text rendering and belongs in the Python TUI layer.

## Tests

1. Update `tests/ace/tui/widgets/test_agent_memory_reads.py`.

   Change the long-reason test to assert every rendered reason and continuation line has `cell_len(line) <= 80`, rather
   than checking only the substring after `↳`.

2. Add coverage for attributed rows.

   Add or extend a test with `agent_label="coder"` and a long reason. Assert that:
   - every reason/continuation line is at most 80 cells,
   - continuation lines align with the reason text prefix,
   - the role column remains aligned with existing row rendering.

3. Add direct shared-helper coverage if useful.

   If the lane-level tests become awkward, add focused tests in `tests/ace/tui/widgets/test_agent_context.py` around
   `append_context_reason()` for:
   - ordinary prefix width,
   - attributed prefix width,
   - a single overlong token,
   - Unicode/wide-cell text if supported by the chosen helper.

4. Leave visual snapshots alone unless they fail.

   The existing visual snapshot data appears to use short reasons, so this should not intentionally change PNG goldens.
   If snapshots fail because rendered output genuinely changes, inspect the diff before deciding whether to update them.

## Verification

After implementation:

- Run targeted tests first:

  ```bash
  pytest tests/ace/tui/widgets/test_agent_memory_reads.py tests/ace/tui/widgets/test_agent_context.py tests/ace/tui/widgets/test_prompt_panel_header.py
  ```

- Because this repo requires it after source/test file changes, run:

  ```bash
  just install
  just check
  ```

## Risks and Mitigations

- A naive `textwrap.wrap(width=64)` would satisfy ordinary rows but fail attributed rows. Computing available width from
  the actual prefix avoids that.
- Python `len()` can drift from terminal columns for glyphs or wide characters. Rich cell measurement avoids that
  mismatch.
- Splitting long tokens can look less polished, but it is required to preserve the strict 80-column limit for unbroken
  strings such as URLs or long identifiers.
- The helper runs only while rendering already-loaded detail text and over at most a few visible context rows, so this
  should not add meaningful TUI latency or affect the Agents list refresh path.
