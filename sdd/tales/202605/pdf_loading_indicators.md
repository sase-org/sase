---
create_time: 2026-05-09 03:08:51
status: done
prompt: sdd/prompts/202605/pdf_loading_indicators.md
---
# Better Loading Indicators For Markdown PDF Construction

## Problem

Markdown-to-PDF work can take long enough that users currently see a gap with little context:

- Agent finalization collects changed Markdown files, renders up to `MAX_MARKDOWN_PDF_ATTACHMENTS` PDFs in
  `src/sase/attachments/markdown_pdf.py`, then writes `done.json` and sends completion notifications.
- The terminal artifact viewer renders Markdown to a transient PDF and then rasterizes it with `pdftoppm` before
  anything appears in the viewer pane.

Both paths are best-effort and subprocess-heavy. Users need to know that SASE is still working, which file is being
processed, how far through the queue it is, and what happened if a file is skipped or conversion falls back to another
engine.

## Product Goal

Show concise, durable progress while PDF construction is active:

- Start: "Preparing PDFs from Markdown..." with discovered count and the attachment cap.
- Per file: current source, ordinal progress, selected engine attempt, and completion/failure.
- End: generated count, skipped count, and any limit/dependency reason.

The status should be visible in the place the user is waiting:

- `sase run` / agent logs should print structured, human-readable phase lines during finalization.
- `sase ace` should be able to reflect the active finalization phase from `workflow_state.json`.
- The artifact viewer pane should print a small pre-render status before Markdown-to-PDF and PDF-to-PNG conversion
  begins.

## Technical Design

1. Add a small progress callback contract to `src/sase/attachments/markdown_pdf.py`.

   Introduce a frozen dataclass such as `MarkdownPdfProgressEvent` with fields:
   - `stage`: `started`, `source_started`, `engine_started`, `source_succeeded`, `source_failed`, `skipped`, `completed`
   - `source_path`, `pdf_path`, `engine`
   - `index`, `total`, `generated`, `skipped`
   - `reason`

   Add an optional `progress` callable argument to `render_markdown_pdf_attachments()` and `render_markdown_pdf()`.
   Existing callers keep the current behavior when no callback is supplied.

2. Make finalization publish progress in two channels.

   In `src/sase/axe/run_agent_exec.py`, wrap the PDF rendering call with a progress handler that:
   - prints short status lines to stdout so command logs show what is happening;
   - updates the current `workflow_state.json` with a transient `pdf_status` object and a readable `activity` string
     while finalization is active;
   - clears or marks that object completed before writing `done.json`.

   Keep this metadata additive so older readers ignore it. Avoid changing terminal statuses unless the TUI deliberately
   adopts the new activity field.

3. Teach the TUI loaders/renderers to surface finalization activity.

   Extend the workflow state wire/filesystem loaders to carry optional activity/finalization fields into `WorkflowEntry`
   / `Agent.step_output` or a dedicated lightweight field. Then update the agent row/detail rendering to show a compact
   suffix such as:
   - `PDF 2/5 docs/notes.md`
   - `PDFs done 4/5`
   - `PDFs skipped: over attachment limit`

   Do not over-style this as a new top-level agent status unless necessary; the row can remain `RUNNING` while the
   suffix tells the user why it is still running.

4. Improve the artifact viewer's own loading message.

   In `src/sase/ace/tui/graphics/_viewer_loop.py` or `_viewer_render.py`, print a compact Rich status panel before
   expensive work:
   - "Rendering Markdown as PDF..."
   - "Converting PDF pages..."
   - dependency/failure warnings already exist and should remain the terminal error path.

   This covers the tmux pane case where the user otherwise stares at an empty split while pandoc and `pdftoppm` run.

5. Preserve failure semantics and limits.

   Keep PDF generation best-effort:
   - Missing `pandoc` or PDF engines should emit a progress skip reason and return `None` as today.
   - Engine fallback should report the attempted engine without treating fallback as fatal.
   - More than `MAX_MARKDOWN_PDF_ATTACHMENTS` Markdown files should report a clear skipped/limited reason instead of
     silently doing no PDF work.

## Test Plan

Add focused tests rather than broad UI snapshots:

- `tests/test_markdown_pdf.py`
  - callback event ordering for successful attachment rendering;
  - events for missing dependency, unsupported source, failed source, and engine fallback;
  - no behavior change when `progress=None`.

- `tests/test_axe_run_agent_exec.py`
  - finalization prints PDF progress lines;
  - `workflow_state.json` receives transient/completed PDF status metadata;
  - above-limit Markdown source counts produce an explicit status reason.

- TUI loader/render tests
  - workflow state activity metadata is parsed by filesystem and snapshot loaders;
  - agent row/detail displays a compact PDF activity suffix without changing the core status.

- `tests/ace/tui/artifact_viewer/test_rendering.py`
  - Markdown artifact rendering announces the Markdown-to-PDF and PDF-to-PNG phases before returning pages or warnings.

## Verification

After implementation, run:

```bash
just install
just test tests/test_markdown_pdf.py tests/test_axe_run_agent_exec.py tests/ace/tui/artifact_viewer/test_rendering.py
just check
```

If the TUI loader/render changes touch additional focused tests, include those test files in the first targeted run
before `just check`.
