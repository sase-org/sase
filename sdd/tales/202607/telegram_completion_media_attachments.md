---
create_time: 2026-07-06 15:49:51
status: done
prompt: sdd/prompts/202607/telegram_completion_media_attachments.md
---
# Plan: Telegram Completion Media Attachments

## Goal

When a successful SASE agent adds or modifies media files, completion delivery should behave like the existing generated
image flow: record the files in the completion metadata, append them to the agent completion notification, and let the
Telegram plugin send them alongside the completion message.

This should cover:

- Existing image behavior, including GIFs, without regressing PNG/JPEG/WebP delivery.
- New generated video attachments, starting with MP4 and a small set of common video suffixes.
- Telegram-specific delivery through the right Bot API methods where practical, with a document fallback when Telegram
  rejects a media-specific send.

## Current Understanding

Core SASE already discovers generated image paths from the agent workspace in `src/sase/axe/image_attachments.py`.
Supported image suffixes currently include `.gif`, and the finalization flow persists the list as
`done.json.image_paths`. Those paths flow through `AgentExecResult`, runner shutdown state,
`send_completion_notification()`, and finally `Notification.files`.

The Telegram plugin does not need a new notification schema field. Its formatter already preserves existing files from
`Notification.files` for `user-agent` workflow completion notifications. The outbound script then dispatches by file
extension: images go through `send_photo`, PDFs go through `send_document`, and other files are converted to PDF when
possible or sent as documents.

That means GIF and MP4 support has two separate gaps:

- GIFs are already discovered, but Telegram currently treats `.gif` as a photo. Animated GIFs should be routed through
  `send_animation`, with fallback to `send_document`.
- MP4 files are not part of the generated-image discovery contract, so they are not automatically recorded or appended
  to agent completion notifications. They need a SASE-side media/video attachment list.

The SASE agent-scan wire also projects `done.json.image_paths` in both Python and the linked Rust core. Any new
`done.json` field that needs to be visible to loaders, ACE, or parity tests should be added on both sides.

## Design

Keep the existing `image_paths` contract intact and add a parallel `video_paths` contract for generated video files.

Do not broaden `image_paths` to mean all media. Keeping videos separate avoids breaking consumers that assume image
preview semantics for `image_paths`, and it lets Telegram choose `send_animation` for GIFs while using `send_video` or
document fallback for real videos.

Use the same discovery algorithm and ordering as images:

1. tracked changes relative to `HEAD`
2. untracked files
3. paths referenced by the saved diff
4. latest commit paths when the agent committed or opened a PR

Resolve paths to existing absolute files, ignore deleted/missing/unsupported files, and dedupe against the already
attached chat, diff, generated PDF, and image paths. Append videos after generated images and before explicit artifacts.

Initial supported video suffixes should be conservative:

- `.mp4`
- `.m4v`
- `.mov`
- `.webm`

Telegram routing should classify attachments as:

- `.gif` -> `send_animation`
- `.mp4`, `.m4v`, `.mov`, `.webm` -> `send_video`
- static images `.png`, `.jpg`, `.jpeg`, `.webp` -> `send_photo`
- PDFs -> `send_document`
- everything else -> existing Markdown-to-PDF/document behavior

If `send_animation` or `send_video` fails for a file, retry that attachment as a document. This preserves delivery for
codec/container cases Telegram cannot render inline.

## Implementation Steps

1. Extend SASE generated attachment discovery.

   In `src/sase/axe/image_attachments.py`, add `SUPPORTED_VIDEO_EXTENSIONS`, `_is_supported_video_path()`, and
   `collect_agent_video_paths()` using the existing generic `_collect_agent_attachment_paths()` helper. Keep
   `collect_agent_image_paths()` unchanged so GIF remains an image attachment from SASE's perspective.

2. Thread `video_paths` through runner finalization.

   Update:
   - `src/sase/axe/run_agent_exec_types.py`
   - `src/sase/axe/run_agent_exec_finalize.py`
   - `src/sase/axe/run_agent_runner.py`
   - `src/sase/axe/run_agent_runner_lifecycle.py`
   - `src/sase/axe/run_agent_runner_finalize.py`
   - `src/sase/axe/run_agent_markers.py`

   The final notification file order should be:

   `chat -> diff -> failure extras if applicable -> markdown PDFs -> image_paths -> video_paths -> explicit artifacts`

   `done.json` should include `video_paths: []` for completed runs, mirroring `image_paths`.

3. Update SASE metadata consumers.

   Add `video_paths` to:
   - `src/sase/core/agent_scan_wire_markers.py`
   - `src/sase/core/agent_scan_wire_conversion.py` if constructor compatibility requires it
   - `src/sase/ace/tui/models/_loaders/_done_loaders.py`

   The Agents tab completed-agent file list should include videos after PDFs and images. Videos can remain ordinary file
   artifacts for ACE unless a later UI change adds video preview support.

   Consider whether `src/sase/core/agent_artifact_defaults.py` should synthesize/persist generated videos. For this
   feature's Telegram requirement, notification delivery only needs `Notification.files`; however, preserving generated
   videos in the artifact picker after workspace cleanup is the closest match to the current image behavior. If added,
   store videos as kind `file` unless the artifact kind enum is deliberately extended to include `video`.

4. Update the linked Rust core scanner.

   In `sase-core`, add `video_paths: Vec<String>` to `DoneMarkerWire`, parse it in
   `crates/sase_core/src/agent_scan/scanner.rs`, and extend the agent-scan parity fixture/assertions in
   `crates/sase_core/tests/agent_scan_parity.rs`.

   This keeps the Python and Rust scan projections aligned before the Python facade relies on the new field.

5. Update Telegram media sending.

   In `sase-telegram`:
   - add `send_animation()` and `send_video()` wrappers in `src/sase_telegram/telegram_client.py`
   - import them in `src/sase_telegram/scripts/sase_tg_outbound.py`
   - replace the current image-only attachment branch with a small attachment classifier/helper
   - route GIFs to animation, videos to video, static images to photo, PDFs to document, and preserve existing
     chat/diff/Markdown conversion behavior
   - add document fallback for animation/video send failures

6. Update docs.

   In SASE docs, update:
   - `docs/agent_images.md`
   - `docs/axe.md`
   - `docs/notifications.md`

   Clarify that generated GIFs remain in `image_paths`, generated videos are stored in `video_paths`, and both are
   appended to `Notification.files`.

   In `sase-telegram`, update:
   - `docs/outbound.md`
   - `README.md`

   Document Telegram routing for static images, GIF animations, videos, PDFs, and fallback documents.

## Tests

SASE repo:

- Extend `tests/test_run_agent_runner_notifications.py` to assert `video_paths` append order and dedupe.
- Extend `tests/test_axe_run_agent_exec_finalize_attachments.py` to create a changed MP4 and assert:
  - `AgentExecResult.video_paths`
  - `done.json.video_paths`
  - notification `extra_files` order
- Extend image attachment tests or add video-specific tests for working tree, diff-file, head-commit, deleted/missing,
  unsupported suffix, and dedupe behavior.
- Extend done-loader tests if existing coverage does not already exercise `extra_files` from `done.json`.
- Run `just install` first, then `just check`.

SASE core:

- Extend Rust scanner parity tests for `video_paths`.
- Run `cargo fmt --all -- --check` and `cargo test --workspace`, or run the SASE repo's `just rust-check` with the
  linked core checkout configured.

SASE Telegram:

- Extend `tests/test_telegram_client.py` for `send_animation()` and `send_video()` wrappers.
- Extend `tests/test_outbound.py` for:
  - GIF uses `send_animation`, not `send_photo`
  - MP4 uses `send_video`
  - media send failure falls back to `send_document`
  - static images and PDFs keep existing behavior
- Extend `tests/test_formatting.py` only if needed to assert workflow-complete attachments preserve video files.
- Run `just check`.

## Risks and Mitigations

- Telegram media APIs can reject files based on codec, size, or container even when the suffix looks right. Mitigate by
  falling back to `send_document` for animation/video failures.
- Adding a new `done.json` field can drift between Python and Rust scanner projections. Mitigate by updating both
  scanners and parity tests in the same change set.
- Treating videos as image artifacts in ACE would imply preview support that does not exist. Mitigate by keeping
  generated videos separate as `video_paths` and displaying them as normal file artifacts unless a later UI feature adds
  video-specific viewing.
- GIF behavior is currently partly supported and partly wrong. Mitigate by leaving SASE's `image_paths` compatibility
  alone and only changing Telegram's send method for `.gif`.

## Acceptance Criteria

- A successful agent that adds or modifies a `.gif` has that GIF attached to its Telegram completion message via
  animation delivery or document fallback.
- A successful agent that adds or modifies a `.mp4` has that MP4 recorded in `done.json.video_paths` and attached to its
  Telegram completion message via video delivery or document fallback.
- Existing PNG/JPEG/WebP/PDF/chat/diff completion attachments keep their current order and behavior.
- Python and Rust agent-scan projections agree on the new `video_paths` field.
- The SASE, SASE core, and SASE Telegram focused tests pass, followed by the relevant repo checks.
