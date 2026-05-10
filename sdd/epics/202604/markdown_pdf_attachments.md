---
create_time: 2026-04-30 04:23:24
bead_id: sase-1j
status: done
prompt: sdd/prompts/202604/markdown_pdf_attachments.md
---

# Plan: Markdown PDF Attachments for Agent Outputs

## Goal

Add first-class support for PDFs generated from Markdown files that SASE agents add or modify. The feature should mirror
the new image attachment integration:

- core SASE discovers Markdown files touched by the completed agent
- core SASE renders those Markdown files to PDF artifacts
- the generated PDFs are attached to the agent completion notification
- Telegram and Google Chat attach those PDFs to the corresponding completion message/thread
- Telegram no longer has special `sdd/research/*.md` diff parsing and PDF generation

This plan is split so each phase can be handled by a distinct agent instance. Each phase should land with tests and
should keep contracts narrow enough for the next phase to build on.

## Current Context

Relevant core SASE files:

- `src/sase/axe/image_attachments.py` discovers touched image files from local changes, untracked files, saved diffs,
  and optionally `HEAD~1..HEAD`.
- `src/sase/axe/run_agent_exec.py` calls `collect_agent_image_paths()` after workflow completion and writes
  `image_paths` into `done.json`.
- `src/sase/axe/run_agent_runner_finalize.py::send_completion_notification()` appends `image_paths` to
  `notify_workflow_complete(extra_files=...)`.
- `src/sase/axe/run_agent_phases.py::build_done_marker()` persists `image_paths`.
- `src/sase/core/agent_scan_wire.py::DoneMarkerWire` and `src/sase/ace/tui/models/_loaders/_done_loaders.py` expose
  `image_paths` to completed-agent file panels.
- `docs/agent_images.md` documents the current image contract.

Relevant plugin files:

- `../sase-telegram/src/sase_telegram/scripts/sase_tg_outbound.py` already converts ordinary Markdown attachments to PDF
  before sending, sends images via `send_photo()`, and has the existing special case that parses diffs for newly added
  `sdd/research/*.md` files.
- `../sase-telegram/src/sase_telegram/pdf_convert.py` contains a Pandoc-based Markdown-to-PDF helper.
- `../retired chat plugin/src/retired_chat_plugin/scripts/sase_gc_outbound.py` already converts non-image Markdown attachments to PDF
  before `gchat_client.upload_file()`.
- `../retired chat plugin/src/retired_chat_plugin/pdf_convert.py` is a near-duplicate Pandoc-based converter.
- Both chat plugins already preserve existing `Notification.files` entries for workflow-complete notifications.

## Design Decisions

Use the existing `Notification.files` list as the cross-process attachment contract. Do not add a new notification
schema field unless a later phase proves that typed attachments are required.

Generate Markdown PDFs in core SASE during agent completion, not in Telegram/GChat. This matches the image integration
and avoids plugin-specific scans of source diffs. Plugins should become delivery layers for already-produced artifacts,
while retaining their existing conversion fallbacks for older notifications and plan/user-response Markdown files.

Store generated PDFs under the current agent artifacts directory, not beside the source Markdown file in the workspace.
That avoids creating extra dirty workspace files and gives cleanup the same lifecycle as other run artifacts. A
suggested layout is:

```text
<artifacts_dir>/markdown_pdfs/<sanitized-relative-source-path>.pdf
<artifacts_dir>/markdown_pdfs/index.json
```

Persist a simple `markdown_pdf_paths` list in `done.json`. If source-to-PDF traceability is useful, also write an
internal `markdown_pdfs/index.json` sidecar with records like `{source_path, pdf_path}`; keep `done.json` itself simple.

PDF rendering should be best-effort. A missing Pandoc/PDF engine or a conversion failure should never fail the agent
run. It should log enough detail for debugging and simply omit the failed PDF attachment.

Discovery should include Markdown files that were added, copied, renamed, modified, or left untracked by the agent. It
should exclude deleted/missing paths and generated PDF artifacts. Suggested extensions: `.md` and `.markdown`.

## Phase 1: Core Attachment Discovery Refactor

Repo: `sase`

Objective: create a reusable touched-file discovery foundation for images and Markdown without changing outward behavior
yet.

Scope:

- Refactor `src/sase/axe/image_attachments.py` into a more general attachment discovery module, or add a sibling helper
  that reuses the same internal git/diff parsing logic.
- Preserve the current image public API so existing tests keep passing: `collect_agent_image_paths(...)` and
  `append_unique_paths(...)`.
- Add Markdown discovery, for example `collect_agent_markdown_paths(...)`, using the same source order as images: local
  tracked changes, untracked files, saved diff, optional head commit.
- Return absolute paths for existing Markdown source files.
- Exclude deleted files, missing paths, directories, and generated artifacts under the run artifacts directory.
- Add focused unit tests next to `tests/test_run_agent_runner_notifications.py` or a new attachment test module:
  added/modified Markdown, untracked Markdown, diff-only clean-tree Markdown, head-commit Markdown, renamed Markdown,
  deleted/missing Markdown, non-Markdown exclusion, and dedupe/order behavior.

Exit criteria:

- Existing image tests still pass.
- Markdown collection is tested independently but not yet wired into completion notifications.
- Run `just install` if needed, then `just check` in `sase`.

## Phase 2: Shared Markdown-to-PDF Renderer in Core

Repo: `sase`

Objective: add a core PDF rendering helper that can be used by completion finalization and, later, by plugins.

Scope:

- Add a small core module such as `src/sase/attachments/markdown_pdf.py`.
- Move or replicate the Pandoc command construction currently duplicated in `sase-telegram` and `retired chat plugin`, with
  conservative behavior:
  - accept only Markdown source paths
  - choose an available PDF engine from `wkhtmltopdf`, `xelatex`, `pdflatex`
  - use a bounded timeout
  - return `None` on missing tools/failure
  - write output to a caller-provided destination path
- Keep external dependencies unchanged; use `subprocess` and existing host tools rather than adding a Python PDF stack.
- Add a minimal PDF stylesheet only if needed. If core owns a stylesheet, plugins should later stop carrying divergent
  copies.
- Add tests that mock `shutil.which()` and `subprocess.run()` rather than requiring Pandoc in CI.

Exit criteria:

- Core exposes a stable helper that converts `source.md` to an explicitly requested `dest.pdf`.
- Conversion failures are non-fatal and leave no partial PDF behind.
- Run `just install` if needed, then `just check` in `sase`.

## Phase 3: Core Completion Wiring and Done Marker Contract

Repo: `sase`

Objective: generate PDFs for touched Markdown files on successful agent completion and attach them to the completion
notification.

Scope:

- In `src/sase/axe/run_agent_exec.py`, after `step_output`/`diff_path` are known and using the same
  `include_head_commit` decision as images, collect touched Markdown source files.
- Render each source Markdown file into `<current_artifacts_dir>/markdown_pdfs/`.
- Dedupe PDFs against existing notification files and image files while preserving stable ordering.
- Extend `build_done_marker()` with `markdown_pdf_paths: list[str] | None = None`; completed markers should include
  `markdown_pdf_paths` with an empty list when no PDFs were generated.
- Extend `_AgentExecResult` and `send_completion_notification()` so generated PDFs are appended to `extra_files`.
  Suggested ordering: `saved_path`, `diff_path`, generated Markdown PDFs, image paths, then failure-only files where
  current failure order requires them. Keep existing failure behavior intact; Markdown PDFs should only be generated for
  successful completed runs.
- Write `markdown_pdfs/index.json` if Phase 2 exposed source mapping.
- Add tests for notification attachment order/dedupe and done marker persistence.
- Update `src/sase/core/agent_scan_wire.py`, Rust scan wire expectations if required by the generated bindings, and
  `src/sase/ace/tui/models/_loaders/_done_loaders.py` so completed-agent file panels include `markdown_pdf_paths`
  alongside plan files and images.
- Update or add docs near `docs/agent_images.md`, either renaming it to a broader attachment doc or adding
  `docs/agent_attachments.md`.

Exit criteria:

- A completed agent that creates/modifies `docs/foo.md` records the generated PDF path in `done.json`.
- The same PDF path appears in `notify_workflow_complete(extra_files=...)`.
- Completed agents loaded from `done.json` can show/cycle the generated PDF in the file panel.
- Run `just install` if needed, then `just check` in `sase`.

## Phase 4: Telegram Delivery and Research Special-Case Removal

Repo: `sase-telegram`

Objective: make Telegram treat core-generated Markdown PDFs as normal completion attachments and remove the obsolete
`sdd/research/*.md` diff parser.

Scope:

- Remove `_RESEARCH_MD_PATH_RE`, `_parse_research_sections()`, `_extract_new_file_content()`,
  `_extract_research_from_diffs()`, and the `research_entries`/`filtered_diff_temps` flow from
  `src/sase_telegram/scripts/sase_tg_outbound.py`.
- Simplify workflow-complete formatting calls so `has_research` and `has_non_research_diff` are no longer driven by diff
  parsing. Keep the normal diff indicator based on actual diff attachments.
- Ensure PDFs already present in `attachments` are sent via `send_document()` without another conversion attempt. The
  existing `md_to_pdf()` helper returns `None` for non-`.md` files, but add a direct test for `.pdf` attachments.
- Preserve existing behavior for:
  - chat transcript response extraction
  - response Markdown to PDF conversion
  - embedding diff content into the response PDF
  - image attachments via `send_photo()`
  - plan approval PDFs
- Keep `sase_telegram.pdf_convert.md_to_pdf()` for legacy Markdown attachments and plan/response flows. Do not delete it
  in this phase unless Phase 2 has already migrated all callers to the core helper.
- Update tests:
  - workflow-complete notification with an attached PDF calls `send_document(chat_id, pdf_path)`
  - mixed chat + diff + core-generated PDF + image sends response PDF, generated PDF document, and image photo
  - old research-diff-specific tests are removed or rewritten to prove research files are no longer parsed from diffs
  - dry-run output lists attached PDFs but no longer prints a separate `Research files:` line

Exit criteria:

- Telegram relies on `Notification.files` for Markdown-derived PDFs.
- No outbound code path parses diffs looking specifically for `sdd/research/*.md`.
- Run `just install` if needed, then `just check` in `sase-telegram`.

## Phase 5: Google Chat Delivery Hardening

Repo: `retired chat plugin`

Objective: verify and harden Google Chat delivery for core-generated Markdown PDFs.

Scope:

- Ensure `format_notification()` preserves workflow-complete PDF attachments exactly like current image attachments.
- In `src/retired_chat_plugin/scripts/sase_gc_outbound.py`, make the attachment upload decision explicit:
  - image files upload directly
  - existing `.pdf` files upload directly
  - Markdown files use `md_to_pdf()` fallback behavior
  - other files upload as-is
- Preserve thread association for every uploaded attachment.
- Keep `retired_chat_plugin.pdf_convert.md_to_pdf()` for plan approval and legacy Markdown attachments unless Phase 2 has already
  migrated it to the core helper.
- Add tests:
  - workflow-complete notification with a generated PDF uploads that PDF in the completion thread
  - mixed Markdown + generated PDF + image does not attempt to convert the PDF
  - missing generated PDF attachments are skipped without failing the notification

Exit criteria:

- A PDF already listed in `Notification.files` is uploaded directly to the same thread as the completion message.
- Existing plan Markdown-to-PDF behavior remains unchanged.
- Run `just install` if needed, then `just check` in `retired chat plugin`.

## Phase 6: Optional Plugin Converter Consolidation

Repos: `sase-telegram`, `retired chat plugin`, possibly `sase`

Objective: remove duplicated Markdown-to-PDF converter implementations after the core helper is stable.

Scope:

- Update `sase_telegram.pdf_convert.md_to_pdf()` and `retired_chat_plugin.pdf_convert.md_to_pdf()` to delegate to the new core
  helper, preserving their public function names so plugin call sites and tests remain stable.
- Decide whether plugin CSS files should remain plugin-specific or be replaced by a shared core stylesheet.
- Keep compatibility with environments where plugins are installed against an older `sase` only if that matters for the
  deployment model; otherwise bump the plugin dependency expectation naturally through the editable workspace.
- Add or adjust tests in both plugin repos so mocked converter behavior still exercises the public plugin function.

Exit criteria:

- There is one implementation of Pandoc command construction.
- Plugin tests still pass.
- Run `just install` if needed, then `just check` in each modified plugin repo.

## Phase 7: End-to-End Verification

Repos: `sase`, `sase-telegram`, `retired chat plugin`

Objective: prove the full cross-repo behavior after the implementation phases land.

Scope:

- In a disposable git workspace, run or simulate an agent completion that creates:
  - `sdd/research/example.md`
  - `docs/notes.md`
  - an image file, to verify image behavior was not regressed
- Confirm the completed run writes:
  - `done.json["markdown_pdf_paths"]`
  - `done.json["image_paths"]`
  - generated PDFs under `markdown_pdfs/`
- Confirm the workflow-complete notification includes the generated PDF paths in `Notification.files`.
- Telegram dry-run should show the PDFs as ordinary attachments and no research-specific output.
- Google Chat dry-run should show the PDFs as ordinary attachments.
- If feasible, run mocked outbound tests for both plugins with a notification containing `saved_path`, `diff_path`,
  `markdown_pdf_paths`, and `image_paths`.

Exit criteria:

- `just check` passes in every modified repo.
- The docs describe the new attachment contract and mention that Markdown PDF generation is best-effort.

## Risks and Open Questions

- PDF generation depends on host tools. Treat missing tools as a non-fatal omission and make this visible through logs.
- Converting every touched Markdown file could be noisy for large documentation changes. If this becomes a problem, add
  a later config knob or size limit; do not start with path-specific exceptions such as `sdd/research/`.
- Generated PDF filenames must avoid collisions for files with the same basename in different directories.
- The core collector should not include generated PDFs or temporary response Markdown files as source Markdown.
- Existing chat plugins still convert response/plan Markdown to PDF. That is intentional: the new feature targets
  Markdown files agents create or modify in the workspace, while response/plan Markdown is a separate notification
  surface.
