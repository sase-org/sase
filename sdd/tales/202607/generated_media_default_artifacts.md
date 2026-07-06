---
create_time: 2026-07-06 16:33:18
status: done
prompt: sdd/prompts/202607/generated_media_default_artifacts.md
---
# Plan: Generated Media Default Artifacts

## Goal

Make every generated media type supported by completion attachments automatically appear in the SASE artifact list, with
the same durability guarantees users already get for generated images.

This should cover:

- Existing generated image files: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`
- Generated video files added by the recent completion-media work: `.mp4`, `.m4v`, `.mov`, `.webm`
- Prompt-referenced media where SASE already has a default-artifact discovery pattern for images

The result should be that a successful agent run that adds, modifies, or references one of these supported files exposes
it from the Agents-tab artifact picker and keeps it available after the numbered workspace is cleaned up.

## Current Understanding

The completion path already discovers modified images and videos separately:

- `done.json.image_paths` records supported image paths, including GIFs.
- `done.json.video_paths` records supported video paths.
- `run_agent_exec_finalize._collect_default_artifacts()` calls `persist_default_agent_artifacts()` with both lists.

The default-artifact layer also already has the concept needed for this feature:

- `store_default_agent_artifact()` persists an auto-discovered file in the global artifact store and writes a
  non-explicit artifact index row.
- `list_agent_artifacts()` merges chat/plan defaults, indexed artifacts, and legacy synthesized defaults.
- Existing generated videos are stored as kind `file`, which is appropriate until ACE has a dedicated video preview
  mode.

The remaining gap is that the artifact default code is still shaped around images:

- Prompt-file discovery is named and implemented as `_discover_prompt_image_paths()`.
- The persistence path derives video-vs-image by path membership instead of carrying typed media candidates.
- Tests cover direct `video_paths` persistence in the facade, but there is not enough end-to-end regression coverage
  proving a modified generated video becomes a durable default artifact through finalization.
- Docs still emphasize "prompt-referenced images" and should make the broader generated-media artifact contract
  explicit.

## Design

Keep the completion metadata contract unchanged:

- Images and GIFs remain in `image_paths`.
- Videos remain in `video_paths`.
- Do not introduce a `video` artifact kind in this change. Persist generated videos as `file` artifacts, because ACE
  does not yet have video preview semantics and the artifact viewer already has a generic file fallback.

Generalize the default-artifact implementation from "image paths" to "media candidates":

- Represent each default media candidate with its source path, artifact kind, label fallback, and ordinal prefix.
- Build candidates from `image_paths`, then `video_paths`, then prompt-referenced media discovered from saved prompt
  artifacts.
- Deduplicate by resolved source path before persisting or synthesizing fallback artifacts.
- Keep generated/done-marker media before prompt-referenced media so files actually produced by the agent remain the
  first media artifacts users see.

Prompt discovery should scan the same saved prompt files it scans today:

- `raw_xprompt.md`
- sibling `*_prompt.md` files, excluding commit-finalizer follow-up prompts

It should accept supported image and video suffixes. Existing prompt-referenced image behavior remains unchanged; prompt
references to supported videos become default `file` artifacts.

## Implementation Steps

1. Generalize prompt media discovery in `src/sase/core/agent_artifact_defaults.py`.

   Rename the image-only regex/helper conceptually to media discovery, add supported video suffixes, and return typed
   candidates instead of bare strings. Keep path resolution behavior unchanged: absolute paths, home-relative paths, and
   workspace-relative paths are accepted only if the resolved file exists.

2. Make persistence use typed media candidates.

   In `persist_default_agent_artifacts()`, build a single ordered candidate list from:
   - `image_paths` as kind `image`
   - `video_paths` as kind `file`
   - prompt-discovered images as kind `image`
   - prompt-discovered videos as kind `file`

   Store each candidate through `store_default_agent_artifact()` with the correct kind and a useful label fallback
   (`Image` or `Video`). Keep missing-file and duplicate handling best-effort and non-fatal.

3. Update legacy synthesis.

   In `synthesize_default_agent_artifacts()`, when `default_artifacts_persisted` is absent, synthesize the same typed
   media candidates from `done.json` plus prompt files. This preserves old agent rows that predate persisted default
   artifacts while adding video parity.

4. Strengthen finalization integration coverage.

   Extend the existing finalization attachment test so a generated MP4 is not only present in `AgentExecResult` and
   `done.json.video_paths`, but also appears in `list_agent_artifacts()` as a persisted non-explicit `file` artifact.
   Include a workspace-cleanup assertion so the test proves durability, not just in-workspace discovery.

5. Add focused artifact-facade tests.

   Cover:
   - prompt-referenced videos are persisted as default `file` artifacts
   - prompt-referenced GIFs remain `image` artifacts
   - dedupe across `image_paths`, `video_paths`, and prompt references is stable
   - legacy synthesis without `default_artifacts_persisted` includes prompt-referenced videos

6. Update docs.

   Update `docs/agent_images.md` to describe "generated media default artifacts" rather than image-only prompt artifact
   behavior. Clarify that generated videos appear as ordinary `file` artifacts and that GIFs remain image artifacts.

## Expected Non-Changes

- No `done.json` schema change is needed.
- No notification schema change is needed.
- No Telegram plugin change is needed; Telegram already consumes `Notification.files`.
- No linked Rust scanner change is expected because `video_paths` already exists in scan metadata and this plan only
  changes default artifact persistence/synthesis behavior. If implementation discovers a Rust artifact-default path, add
  the matching Rust change and parity test, but do not invent one just for this feature.
- No new CLI subcommands or options are needed.

## Tests

Run focused tests first:

- `pytest tests/test_agent_artifact_facade.py`
- `pytest tests/test_axe_run_agent_exec_finalize_attachments.py`

Then run the project-required gate:

- `just install`
- `just check`

Because this plan changes source files in the primary SASE repo, `just check` is required before finalizing the
implementation.

## Risks and Mitigations

- Video files can be large. This plan matches existing default-artifact behavior by copying only files SASE already
  discovered or prompt-referenced; it does not recursively scan the workspace.
- Adding a `video` artifact kind now would ripple through viewers and serializers. Store videos as kind `file` for this
  change and leave a dedicated preview kind for a future UI feature.
- Prompt-file regexes can overmatch prose. Preserve the current conservative path-like matching style and require the
  resolved file to exist.
- Current runs mark `default_artifacts_persisted` after best-effort persistence. Preserve that behavior so artifact
  persistence failures never fail an otherwise successful agent run.

## Acceptance Criteria

- A successful agent that modifies a supported video file shows that video in the SASE artifact picker after
  finalization.
- The video artifact is still available after the workspace file is removed, proving it was copied into persistent
  artifact storage.
- Prompt-referenced supported videos are surfaced as default `file` artifacts, matching prompt-referenced image
  behavior.
- GIF behavior does not regress: modified or prompt-referenced GIFs remain image artifacts.
- Existing completion notification ordering and `done.json.image_paths` / `done.json.video_paths` behavior remain
  unchanged.
