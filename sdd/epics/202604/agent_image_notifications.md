---
create_time: 2026-04-30 02:35:23
status: done
bead_id: sase-1i
prompt: sdd/prompts/202604/agent_image_notifications.md
---
# Plan: Agent Image Attachments and Kitty TUI Previews

## Goal

When an agent adds or modifies image files such as PNG/JPEG/WebP/GIF files, the agent completion notification should
carry those image paths so downstream notification senders can attach the images. The same image attachments should be
previewable inside the SASE TUI when running in a Kitty-compatible terminal, specifically in:

- the notifications modal file panel
- the agent entry file panel on the Agents tab

This plan spans `sase`, `sase-telegram`, and `retired chat plugin`. The work should be split across distinct agent instances,
with each phase leaving a narrow, tested contract for the next phase.

## Context

Relevant local findings:

- Core completion notifications are built in
  `src/sase/axe/run_agent_runner_finalize.py::send_completion_notification()`. They currently attach `saved_path` and
  `diff_path`, plus error report/output log on failures.
- Notification storage is the JSONL-backed `Notification.files` list in `src/sase/notifications/models.py` and
  `src/sase/notifications/store.py`.
- The agent loader already exposes `done.json` paths like `response_path`, `diff_path`, and `plan_path` as agent
  `extra_files`, which the Agents tab file panel cycles through.
- The TUI static file preview path is centralized enough for initial wiring:
  - notifications modal: `src/sase/ace/tui/modals/notification_modal.py::_display_file()`
  - agent file panel: `src/sase/ace/tui/widgets/file_panel/_display.py::display_static_file()`
- Recent research in `sdd/research/202604/tui_image_pdf_support.md` recommends Kitty Graphics Protocol with Unicode
  placeholders, probed before `App.run()`, and warns not to rely on direct cursor placement in Textual.
- Recent chat `sase-ace_run-260429_215624` produced the image/PDF research. Recent chat
  `sase-ace_run-it.plan-260430_014836` and the resulting `plans/202604/kitty_tmux_icat.md` cover Kitty/tmux launch
  constraints.
- `sase-telegram` already detects image attachments in `src/sase_telegram/scripts/sase_tg_outbound.py::_is_image_file()`
  and sends those attachments via `send_photo()`, but completion notifications do not currently include touched image
  paths.
- `retired chat plugin` formats workflow-complete notifications in `src/retired_chat_plugin/formatting.py::_format_workflow_complete()`
  and uploads formatted attachments in `src/retired_chat_plugin/scripts/sase_gc_outbound.py`.

## Design Decisions

Use a core notification contract first: `Notification.files` remains the cross-plugin attachment list. Do not add a new
notification schema field unless a later phase proves that typed attachments are necessary.

Discover touched images in core before calling `notify_workflow_complete()`. The helper should identify files added or
modified by the agent, filter by image extension and file existence, and append those paths to `extra_files` after
chat/diff/error files. It should dedupe while preserving order.

Prefer a VCS-aware source of truth over parsing human diff text. For git, `git diff --name-status` plus untracked-file
enumeration is the right shape. Use the existing VCS provider abstractions where practical; add a provider method only
if current APIs cannot safely report local added/modified files. Handle committed/proposal flows where
`commit_diff.diff` exists and the working tree may already be clean.

Kitty TUI rendering should be treated as a local preview feature, independent from notification delivery. The first TUI
implementation should only target raster images, not PDFs, because the user asked for image files and PDF rasterization
adds a bigger dependency/security surface.

## Phase 1: Core Image Attachment Contract

Repo: `sase`

Objective: make agent completion notifications include image files added or modified by the agent.

Scope:

- Add a small image-attachment helper near the agent finalization path, for example `src/sase/axe/image_attachments.py`
  or a focused helper in `run_agent_runner_finalize.py`.
- Define supported image extensions centrally: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`.
- Collect candidate paths from the agent workspace/change context:
  - added or modified tracked files
  - untracked image files
  - committed/proposal diff metadata when the agent committed and the working tree is clean
- Exclude deleted files and missing paths.
- Normalize to absolute paths where possible, because Telegram/GChat outbound chops run outside the agent workspace
  context.
- Dedupe against existing `extra_files`.
- Add image paths to `extra_files` in `send_completion_notification()`.
- Consider also writing the resulting image path list into `done.json`, either as a new `image_paths` key or by ensuring
  the loader can infer it from notification files. Prefer adding `image_paths` if the TUI phase needs stable agent-level
  access independent of notifications.

Tests:

- Unit tests in `tests/test_run_agent_runner_notifications.py` for successful completion with added/modified image
  paths.
- Tests for deleted/missing/non-image paths being ignored.
- Tests for deduplication and ordering.
- If a provider-level method is added, add focused provider tests for git name-status/untracked behavior.

Exit criteria:

- `just install` if needed, then `just check` in `sase`.
- A dry-run or unit-level assertion proves `notify_workflow_complete(extra_files=...)` includes touched image paths.

## Phase 2: Telegram Outbound Attachment Polish

Repo: `sase-telegram`

Objective: ensure completion notifications with image attachments are sent as Telegram photos and remain readable when
mixed with chat/diff artifacts.

Scope:

- Keep using `Notification.files` as the input contract.
- Extend or adjust workflow-complete formatting/tests so image attachments from `user-agent` notifications are preserved
  in the returned attachment list.
- Verify `_run_outbound()` sends image files via `send_photo()` for workflow-complete notifications, not only
  `sender="image"` notifications.
- Ensure image attachments do not get swallowed by response-PDF conversion or diff embedding.
- Decide whether the first image should receive a caption or whether the existing completion message is enough. Keep
  this phase small unless Telegram API behavior requires a caption for context.

Tests:

- Formatter test: workflow-complete notification with `.png`/`.jpg` file returns that file as an attachment.
- Outbound test: workflow-complete notification with an image calls `send_photo()` and does not call `send_document()`
  for that file.
- Mixed attachments test: chat markdown plus diff plus image still sends response/PDF and image correctly.

Exit criteria:

- `just install` if needed, then `just check` in `sase-telegram`.

## Phase 3: Google Chat Outbound Attachment Polish

Repo: `retired chat plugin`

Objective: ensure completion notifications with image attachments are uploaded into the same Google Chat thread as the
completion message.

Scope:

- Keep using `Notification.files` as the input contract.
- Extend workflow-complete formatting/tests so existing image files remain in `FormattedMessage.attachments`.
- In `sase_gc_outbound.py`, avoid unnecessary markdown-to-PDF conversion attempts for image files. Upload images
  directly with `gchat_client.upload_file()`.
- Preserve current plan markdown-to-PDF behavior for markdown documents.
- Ensure each uploaded image is associated with the completion message thread.

Tests:

- Formatter test: workflow-complete notification with image path includes it in attachments.
- Outbound integration test: an image attachment is uploaded with `thread=thread_id`.
- Mixed attachment test: markdown still goes through PDF conversion when appropriate, image uploads directly.

Exit criteria:

- `just install` if needed, then `just check` in `retired chat plugin`.

## Phase 4: Kitty Graphics Foundation In SASE TUI

Repo: `sase`

Objective: add a reusable, tested image preview backend for Kitty-compatible terminals without wiring it broadly yet.

Scope:

- Add a focused TUI graphics package, for example `src/sase/ace/tui/graphics/`.
- Implement capability detection that runs before `AceApp.run()`, likely from `src/sase/main/ace_handler.py`, following
  `sdd/research/202604/tui_image_pdf_support.md`.
- Implement a conservative Kitty TGP renderer:
  - PNG byte transmission with direct/stream transport
  - chunking
  - tmux passthrough wrapping
  - virtual placement and Unicode placeholders
  - cleanup/deletion hooks
- Add a fallback renderable for unsupported terminals, probably metadata plus a simple textual placeholder at first.
  Halfblock previews can be deferred unless this phase remains small.
- Keep dependencies minimal. If Pillow is needed for image dimensioning/downscaling, add it deliberately and pin/declare
  it in project metadata.
- Do not add PDF support in this phase.

Tests:

- Pure unit tests for image-extension detection, ID generation, escape chunking, tmux wrapping, placeholder cell
  generation, and capability env/probe decisions.
- A non-interactive renderable test that does not require a real Kitty terminal.
- Optional manual verification notes using `kitten icat`/Kitty in tmux, but do not make CI depend on terminal graphics.

Exit criteria:

- `just install` if dependencies changed, then `just check` in `sase`.
- A small internal renderable can represent a local PNG path without crashing on non-Kitty terminals.

## Phase 5: Wire Image Previews Into File Panels

Repo: `sase`

Objective: use the graphics foundation in the two requested TUI surfaces.

Scope:

- Notifications modal:
  - Update `NotificationModal._display_file()` to detect image files before UTF-8 text reads.
  - Render the image preview when graphics are available.
  - Render a clear fallback with path, size, and “open in editor” compatibility when unavailable.
- Agent entry file panel:
  - Update `AgentFilePanel.display_static_file()` to detect image files before UTF-8 text reads.
  - Ensure image files in `agent.extra_files` can be cycled with `ctrl+n`/`ctrl+p`.
  - If Phase 1 added `done.json.image_paths`, update agent loaders so completed agents include those image paths in
    `extra_files`.
- Maintain existing behavior for text, markdown, diff, and missing/empty files.
- Ensure image display state is cleaned up when switching files, switching agents, closing the modal, or resizing.

Tests:

- Notification modal tests for image file selection and fallback behavior.
- Agent file panel tests for image file detection and cycling.
- Loader tests if `done.json.image_paths` is added.
- No real Kitty dependency in CI; mock the renderable/capability layer.

Exit criteria:

- `just install` if needed, then `just check` in `sase`.
- Manual TUI smoke test in Kitty: image attachment appears in notification file panel and selected agent file panel.

## Phase 6: End-to-End Hardening

Repos: `sase`, `sase-telegram`, `retired chat plugin`

Objective: close cross-repo gaps after the core/plugin/TUI phases land.

Scope:

- Run an end-to-end local scenario where an agent creates or modifies a PNG/JPEG and completes.
- Confirm the resulting notification JSONL row includes the image path.
- Confirm Telegram dry-run/outbound behavior shows the image as an attachment/photo.
- Confirm GChat dry-run/outbound behavior uploads the image in the completion thread.
- Confirm the TUI can preview the same image from both the notification and agent panels in Kitty, and degrades cleanly
  elsewhere.
- Update docs if there is already a relevant notifications/TUI document; otherwise keep documentation limited to code
  comments/tests.

Tests:

- Full `just check` in every modified repo.
- Manual smoke notes captured in the final phase response.

Exit criteria:

- All modified repos pass `just check`.
- No regressions for text/PDF/diff attachments.
- TUI non-Kitty fallback is usable and does not emit raw escape sequences.

## Phase Dependency Graph

1. Phase 1 blocks Phases 2, 3, and 5 because it defines how image paths reach notifications and agent metadata.
2. Phases 2 and 3 can run in parallel after Phase 1.
3. Phase 4 can run in parallel with Phases 2 and 3 because it only builds TUI graphics infrastructure.
4. Phase 5 depends on Phases 1 and 4.
5. Phase 6 depends on all prior phases.

## Risks

- Core may not have a uniform cross-VCS way to list local added/modified/untracked image files. If so, implement a
  git-backed helper first and keep the provider extension small and explicit.
- If the agent commits before completion, working-tree detection alone may miss images. Phase 1 must cover
  committed/proposal diff metadata or use already-saved diff/name-status artifacts.
- Kitty probing after Textual starts is unreliable. Phase 4 must probe before `App.run()`.
- Direct cursor placement will flicker or leave stale images in Textual. Use Unicode placeholders rather than direct
  placement.
- Image files can be large or malformed. Cap file size/decoded dimensions before previewing in the TUI and fail closed
  to a textual fallback.
