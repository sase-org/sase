---
name: gchat_plan_pdf_attachment
description: Convert plan-approval markdown attachments to PDF before uploading to
  Google Chat, falling back to the raw markdown when conversion is unavailable.
create_time: 2026-04-25 12:14:23
status: done
prompt: sdd/prompts/202604/gchat_plan_pdf_attachment.md
---

# Google Chat: PDF-convert plan attachments (with markdown fallback)

## Problem

When a plan-approval notification fires in the Telegram integration, the plan's markdown file is converted to a PDF (via
pandoc, with a `wkhtmltopdf → xelatex → pdflatex` engine fallback chain) before being attached to the thread. PDFs
render far more readably on phone clients than raw `.md` files, especially for long plans with code blocks and tables.

The Google Chat integration currently uploads the markdown file as-is — no PDF conversion. The infrastructure for the
conversion is already shipped in the gchat plugin (`retired_chat_plugin/pdf_convert.py` is a byte-for-byte copy of the Telegram
version, including `pdf_style.css`), but it is never imported by the outbound script. This plan wires it in.

## Current state

**Outbound attachment loop today** — `retired chat plugin/src/retired_chat_plugin/scripts/sase_gc_outbound.py` lines 163–179:

```python
for attachment_path in formatted.attachments:
    if not Path(attachment_path).expanduser().exists():
        continue
    try:
        gchat_client.upload_file(
            space,
            str(Path(attachment_path).expanduser()),
            thread=thread_id or None,
        )
        rate_limit.record_send()
    except Exception:
        log.warning(
            "Failed to upload attachment %s for notification %s",
            attachment_path,
            n.id[:8],
            exc_info=True,
        )
```

**Reference implementation** — `sase-telegram/src/sase_telegram/scripts/sase_tg_outbound.py` lines 469–474:

```python
pdf_path = md_to_pdf(actual_path)
if pdf_path:
    pdf_temps.append(Path(pdf_path))
    send_document(chat_id, pdf_path)
else:
    send_document(chat_id, actual_path)
```

…with cleanup at the end of the per-notification loop (line 528–529):
`for p in pdf_temps + …: p.unlink(missing_ok=True)`.

**`md_to_pdf` contract** — `retired chat plugin/src/retired_chat_plugin/pdf_convert.py:46`:

- Accepts a string path. Returns the PDF path (string) on success, `None` on any failure mode (non-`.md` suffix, no
  pandoc engine installed, every engine failed, timeout).
- Writes the PDF next to the source file as `<stem>.pdf` (uses `Path.with_suffix(".pdf")`).
- Already handles its own logging on failure paths.

## Goal

For each attachment in `formatted.attachments`:

1. Try to convert to PDF via `md_to_pdf`.
2. Upload the PDF if conversion succeeded; otherwise upload the original file (markdown or anything else).
3. Delete any PDF the converter created after the upload attempt completes (success or failure).
4. Preserve every other property of the existing loop: existence check, rate-limit record on success, log-and-continue
   on exception.

## Design

### Where the change lives

Single-file edit: `retired chat plugin/src/retired_chat_plugin/scripts/sase_gc_outbound.py`. No changes to `formatting.py`, no changes to
`pdf_convert.py`, no changes to the main `sase_100` repo.

### Loop rewrite

Inside the existing per-notification block, replace the attachment loop with the following shape (sketch — exact
formatting/comments TBD during implementation):

```python
pdf_temps: list[Path] = []
for attachment_path in formatted.attachments:
    src = Path(attachment_path).expanduser()
    if not src.exists():
        continue

    upload_path = str(src)
    pdf_path = md_to_pdf(str(src))
    if pdf_path:
        pdf_temps.append(Path(pdf_path))
        upload_path = pdf_path

    try:
        gchat_client.upload_file(space, upload_path, thread=thread_id or None)
        rate_limit.record_send()
    except Exception:
        log.warning(
            "Failed to upload attachment %s for notification %s",
            upload_path,
            n.id[:8],
            exc_info=True,
        )

for p in pdf_temps:
    p.unlink(missing_ok=True)
```

Key properties:

- `md_to_pdf` is called _before_ the `try`, mirroring Telegram. The conversion already swallows its own errors and
  returns `None` on failure, so it can't take down the loop.
- The PDF temp list is collected as we go and cleaned up unconditionally at the end. Cleanup runs even if an upload
  raised, since we still want to remove the PDF we wrote to disk.
- On the markdown fallback path (`pdf_path is None`) we upload `src` exactly as before — preserving the current behavior
  bit-for-bit when pandoc is absent.
- The fallback is **not** "PDF first, then markdown if PDF upload fails." It's "PDF if conversion succeeds, otherwise
  markdown." This matches Telegram's behavior and the user's stated requirement (one upload attempt per attachment).

### Import

Add at the top of `sase_gc_outbound.py`:

```python
from retired_chat_plugin.pdf_convert import md_to_pdf
```

Co-located with the other `retired_chat_plugin.*` imports already present at lines 20–28.

### Why not factor `md_to_pdf` into the main repo

The existing architecture deliberately ships an identical copy of `pdf_convert.py` and `pdf_style.css` in each plugin
(verified: byte-for-byte identical between `retired chat plugin` and `sase-telegram`). Plugins are independently installable, so
we don't want a hard dependency from the gchat plugin onto the main `sase_100` package for this. Leave the duplication
in place.

## Tests

Add tests to `retired chat plugin/tests/test_integration.py` (or a new dedicated file if `test_integration.py`'s existing fixture
shape is awkward; look at the file first and decide). Each test should drive `sase_gc_outbound.main()` end-to-end with
mocked `gchat_client` and a stubbed `md_to_pdf`:

1. **`md_to_pdf` returns a PDF path** — assert `gchat_client.upload_file` was called with the PDF path, not the source
   markdown path; assert the PDF temp file was deleted after the run.
2. **`md_to_pdf` returns `None`** — assert `upload_file` was called with the original markdown path; assert no PDF
   cleanup attempts (or that cleanup is a no-op).
3. **`upload_file` raises after a successful PDF conversion** — assert the exception is logged and swallowed (the
   existing contract), and assert the PDF temp file is still cleaned up.

Use `monkeypatch.setattr` on `retired_chat_plugin.scripts.sase_gc_outbound.md_to_pdf` so the engine-availability check in the
real implementation isn't exercised in CI.

For prior art, see `sase-telegram/tests/test_inbound.py` lines 1017–1020 (and surrounding context) — the Telegram tests
build a fake PDF path and patch the converter the same way.

## Verification

1. From the active sase_100 workspace: `just install && just check` passes.
2. From `../retired chat plugin`: the gchat plugin's own test suite passes (`pytest` or whatever its `Justfile` exposes — confirm
   during implementation).
3. Manual smoke (optional, dev machine has pandoc installed): trigger a plan-approval notification and confirm the
   thread receives a `.pdf` attachment instead of a `.md` file. If pandoc is uninstalled, confirm the markdown is
   uploaded instead with no error in the log.

## Risks / notes

- **Pandoc availability.** `md_to_pdf` already returns `None` cleanly when no engine is installed, so machines without
  pandoc fall back to the existing markdown upload behavior. No new dependency surface.
- **Non-`.md` attachments.** Today `formatted.attachments` only carries the plan markdown for `PlanApproval`
  notifications, but the loop is generic. `md_to_pdf` returns `None` immediately for non-`.md` suffixes, so passing e.g.
  an image through unchanged Just Works.
- **Race on PDF cleanup.** `gchat_client.upload_file` is synchronous (it shells out to the `gchat` CLI and waits for
  exit), so the PDF is fully consumed by the time we unlink it. No race window with the upload still streaming bytes.
- **Disk usage.** PDFs are small (tens of KB for typical plans) and live for the duration of one outbound run, then
  unlinked. No disk-space concern.
- **Existing `pdf_style.css` is already in place.** No CSS change needed; the styling is shared with Telegram by design.

## Implementation steps

1. Edit `retired chat plugin/src/retired_chat_plugin/scripts/sase_gc_outbound.py`:
   - Add `from retired_chat_plugin.pdf_convert import md_to_pdf` to the imports.
   - Replace the attachment loop (currently lines 163–179) with the version above, plus the trailing `pdf_temps` cleanup
     pass.
2. Add the three tests described in **Tests** above to `retired chat plugin/tests/test_integration.py` (or a new file if it reads
   more cleanly there).
3. Run the gchat plugin's test suite from `../retired chat plugin`.
4. Run `just check` from the sase_100 workspace.
