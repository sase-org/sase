---
create_time: 2026-05-23 21:31:52
status: wip
prompt: sdd/prompts/202605/telegram_multi_image_albums.md
---
# Implementation Plan - Telegram Multi-Image Launches

## Context

Single Telegram image launches already work because `sase-telegram` downloads one photo or image document, builds a
prompt containing the local image path, and launches through `sase.agent.launcher.launch_agents_from_cwd`. Core SASE
then persists the launch prompt as `raw_xprompt.md`; prompt-referenced image discovery already scans that prompt and can
surface referenced image paths as ACE artifacts.

The missing behavior is Telegram albums / media groups. Telegram represents a multi-image send as multiple message
updates with the same `media_group_id`. In the current inbound loop each `msg.photo` or image document is handled
immediately, so an album launches one agent per image and each launched prompt only names a single path.

## Goals

- A user sending multiple images in one Telegram album should get one SASE launch, not one launch per image.
- The launched agent prompt should include every downloaded image path in a plain, path-like form so the agent can read
  all files and existing prompt-image artifact discovery can find them later.
- Single-image photo and image-document behavior should remain immediate and backward compatible.
- Albums should still work when Telegram delivers grouped updates across more than one inbound chop invocation.
- Launch-disabled hosts must not stage, download, or launch image albums.

## Proposed Design

1. Generalize the prompt builder in `src/sase_telegram/inbound.py`.
   - Add a multi-image prompt helper that accepts a sequence of image paths plus an optional caption.
   - Keep `build_photo_prompt()` as the single-image compatibility wrapper.
   - For multiple paths, produce a numbered list such as:
     - `1. /abs/path/first.jpg`
     - `2. /abs/path/second.jpg`
   - Preserve the existing caption-first behavior and normalize Telegram `#workflow@ref` shorthand before wrapping.

2. Add persistent Telegram media-group staging in `src/sase_telegram/scripts/sase_tg_inbound.py`.
   - Introduce a JSON state file under `~/.sase/telegram/`, for example `media_groups.json`.
   - Key records by chat id plus `media_group_id`.
   - Store ordered image items containing at least message id, kind (`photo` or `document`), Telegram `file_id`, and
     enough filename data to generate the final local path later.
   - Store the first non-empty reconstructed caption for the group, plus `first_seen_at` and `last_seen_at`.
   - Deduplicate repeated items by Telegram `file_id` while preserving message order.

3. Change inbound update dispatch for grouped images.
   - If a photo or image document has no `media_group_id`, keep the current immediate single-image handler.
   - If it has `media_group_id`, stage it instead of launching immediately.
   - After all fetched updates are staged, flush media groups whose `last_seen_at` is older than a small quiet window.
   - Flush after processing current updates, not before, so a second album item arriving in a later poll can still join
     an older pending group before the group is considered ready.
   - Also flush ready groups on runs with no new updates, so staged albums complete on the next periodic inbound run.

4. Launch a ready media group as one agent.
   - Create `IMAGES_DIR` once, download each staged file to a stable timestamped filename, and collect the resulting
     paths in group order.
   - If any download fails, send one Telegram error message, do not launch, and remove the staged group after
     best-effort cleanup of files downloaded for that failed launch attempt.
   - Build one multi-image prompt, record project context once, and call `_launch_agent(prompt)` once. Multi-model
     directives in the caption should still fan out inside the canonical launch pipeline, just as single-photo captions
     do today.

5. Update docs.
   - Update `README.md` and `docs/inbound.md` to describe photo/image-document albums as one launch with all local image
     paths.
   - Mention the small delayed launch behavior for albums caused by the quiet window.

## Tests

Add focused coverage in the `sase-telegram` workspace:

- `tests/test_inbound.py`
  - multi-image prompt helper includes all paths and keeps the single-image wrapper output compatible;
  - grouped photo messages are staged without immediate launch;
  - flushing a ready group downloads all images and launches exactly once with all paths in the prompt;
  - grouped updates split across two inbound runs join the same group before launching;
  - grouped image documents preserve document filenames or safe generated names;
  - launch-disabled mode does not stage, download, or launch grouped images;
  - download failure sends one error and does not launch.

- `tests/test_integration.py`
  - end-to-end inbound polling with two photo updates sharing a `media_group_id` saves the offset, then a later run
    flushes one launch containing both downloaded paths.

## Verification

After implementation, run in `../sase-telegram/sase-telegram_11`:

```bash
just install
pytest tests/test_inbound.py tests/test_integration.py
just check
```

If the implementation unexpectedly touches core SASE behavior, also run the narrow core tests around prompt-referenced
image artifacts in this workspace before `just check`.
