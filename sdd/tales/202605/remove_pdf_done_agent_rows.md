---
create_time: 2026-05-09 15:28:59
status: done
prompt: sdd/prompts/202605/remove_pdf_done_agent_rows.md
---
# Remove Completed PDF Text From Agent Rows

## Goal

Remove the completed Markdown-PDF progress text from Agents tab rows, specifically labels like `PDFs done <N>/<M>` and
`PDFs done <N>/<M> (<K> skipped)`, while preserving useful in-progress PDF activity and structured PDF metadata.

## Current Behavior

- The agent runner writes structured `pdf_status` to `workflow_state.json` during Markdown PDF generation.
- The same runner also writes a transient `activity` string derived from that status.
- At the end of PDF generation, `_clear_workflow_pdf_activity()` removes `activity` but intentionally leaves
  `pdf_status`.
- The Agents tab row renderer still derives a fallback label from `agent.pdf_status` when `agent.activity` is empty. For
  completed PDF status, that fallback returns `PDFs done ...`, which is why completed rows still show the text.
- Existing tests currently assert the old behavior for PDF activity suffixes and loader metadata preservation.

## Scope

Change presentation behavior only:

- Keep `pdf_status` loading and cache invalidation intact so detail views, debugging, and future consumers can still
  inspect structured PDF progress.
- Keep active PDF rendering labels visible while PDF work is actually running, such as
  `Preparing PDFs from Markdown...`, `PDF 2/5 docs/notes.md`, and `PDF done 2/5 docs/notes.md`.
- Suppress terminal/completed PDF fallback labels in agent rows, including skipped-over-limit terminal labels.
- Do not remove artifact generation, PDF paths, attachment discovery, or runner logging.

## Implementation Plan

1. Update `_agent_activity_label()` in `src/sase/ace/tui/widgets/_agent_list_render_layout.py`.
   - Continue returning `agent.activity` when explicitly present.
   - Continue deriving labels for active `pdf_status` stages.
   - Return `None` for terminal `pdf_status` stages that should not occupy the row suffix once `activity` has been
     cleared, especially `stage == "completed"` and terminal skipped/failed states when `active` is false.

2. Remove or simplify the styling branch that special-cases `label.startswith("PDFs done")`, since completed labels will
   no longer be rendered in rows.

3. Update tests for row rendering.
   - Replace the old `test_agent_row_displays_pdf_activity_suffix` expectation with coverage that active PDF activity
     still renders.
   - Add/adjust coverage for `pdf_status={"stage": "completed", ...}` so the suffix contains only runtime data, or is
     empty when no runtime suffix applies, and does not contain `PDFs done`.
   - If skipped terminal status is covered, assert it does not render in rows when marked inactive.

4. Leave loader tests that preserve `activity` and `pdf_status` metadata alone unless they directly assert row
   rendering. Metadata preservation is still desirable even if rows no longer display terminal PDF completion text.

5. Run focused tests first:
   - `pytest tests/test_ace_tui_widgets.py tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
   - Add `tests/test_agent_loader_workflow_states.py` if metadata assertions are touched.

6. Run repository validation after implementation per repo instructions:
   - `just install`
   - `just check`

## Risks and Notes

- If historical `workflow_state.json` files still contain an explicit `activity` value of `PDFs done ...`, the renderer
  will continue to honor it. New runs should not leave that explicit value because `_clear_workflow_pdf_activity()`
  already removes `activity` after PDF finalization.
- Suppressing only terminal fallback labels keeps the useful “something is still happening after the LLM response”
  signal without leaving noisy completion summaries on settled rows.
