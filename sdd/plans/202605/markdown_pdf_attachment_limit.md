---
create_time: 2026-05-01 22:06:28
status: done
prompt: sdd/prompts/202605/markdown_pdf_attachment_limit.md
---
# Plan: Limit Markdown PDF Attachments for Large Agent Edits

## Problem

Completed agents currently discover every added or modified Markdown source and render each one into a PDF under the
agent artifacts directory. Those PDF paths are then added to the shared completion notification `files` list. Telegram
and Google chat consume that shared notification payload, so a large Markdown-heavy change can create and send many PDFs
to the user.

The requested behavior is:

- If an agent changed 10 or fewer Markdown files, keep the existing PDF conversion and attachment behavior.
- If an agent changed more than 10 Markdown files, do not render or attach Markdown PDFs.
- In the large-change case, still send the user a completion message that says how many Markdown files were edited.

## Current Flow

The relevant flow is:

1. `src/sase/axe/run_agent_exec.py::_finalize_loop` saves chat history, extracts diff metadata, then calls
   `collect_agent_markdown_paths(...)`.
2. It immediately passes all discovered Markdown paths to
   `sase.attachments.markdown_pdf.render_markdown_pdf_attachments(...)`.
3. The resulting `markdown_pdf_paths` are stored in `done.json`, returned on `_AgentExecResult`, and later passed to
   `send_completion_notification(...)`.
4. `src/sase/axe/run_agent_runner_finalize.py::send_completion_notification` appends those PDFs to `extra_files` and
   writes a shared notification through `notify_workflow_complete(...)`.

Because Telegram and Google chat work from the same notification, the safest product-level fix is in this shared agent
completion path rather than in either chat integration.

## Proposed Design

Add a single threshold constant, `MAX_MARKDOWN_PDF_ATTACHMENTS = 10`, near the Markdown attachment logic.

In `_finalize_loop`:

1. Keep collecting Markdown paths exactly as today, including existing exclusions and de-duplication.
2. Count the discovered Markdown paths after de-duplication.
3. If the count is `<= MAX_MARKDOWN_PDF_ATTACHMENTS`, call `render_markdown_pdf_attachments(...)` as today.
4. If the count is `> MAX_MARKDOWN_PDF_ATTACHMENTS`, skip PDF rendering entirely and leave `markdown_pdf_paths` empty.
5. Return the count on `_AgentExecResult` so notification finalization can mention it.

In `send_completion_notification`:

1. Accept an optional `markdown_source_count`.
2. When `markdown_source_count > MAX_MARKDOWN_PDF_ATTACHMENTS`, append a human-readable note such as
   `Edited 14 Markdown files; skipped PDF attachments because the limit is 10.`
3. Continue attaching chat, diff, failure reports, logs, and image files as before.
4. Keep `markdown_pdf_paths` support unchanged for the normal `<= 10` case.

This keeps the policy centralized, avoids changing the notification schema, and lets Telegram and Google chat receive
the count in the same message text they already forward.

## Test Plan

Add focused tests around existing coverage:

- Update `tests/test_axe_run_agent_exec.py` to assert that 10 Markdown files still render PDFs.
- Add a test with 11 Markdown files proving:
  - `render_markdown_pdf` is not called.
  - `result.markdown_pdf_paths == []`.
  - `result.markdown_source_count == 11`.
  - `done.json["markdown_pdf_paths"] == []`.
- Update `tests/test_run_agent_runner_notifications.py` to assert the completion notification appends the Markdown count
  note when the threshold is exceeded and does not add such a note at the threshold.

## Verification

Run targeted tests first:

```bash
pytest tests/test_axe_run_agent_exec.py tests/test_run_agent_runner_notifications.py tests/test_markdown_pdf.py
```

Because this repo requires it after changes, run:

```bash
just install
just check
```
