---
create_time: 2026-07-06 16:51:31
status: done
prompt: sdd/prompts/202607/video_artifact_preview.md
---
# Plan: Terminal Video Preview for Agent Artifacts (mpv)

## Goal

Give video artifacts the same delightful in-terminal preview experience that image artifacts already have: selecting a
video from the Agents-tab artifact picker opens the familiar right-side tmux artifact pane and _plays the video in the
terminal_ using mpv, with intuitive playback controls, the existing artifact navigation loop, and graceful degradation
when dependencies are missing.

Concretely, after this change:

- Opening an `.mp4`, `.m4v`, `.mov`, or `.webm` artifact plays it inside the artifact viewer pane instead of dumping
  binary garbage through the text viewer (the current behavior, since videos are kind `file`).
- Playback looks and feels like the image viewer: same gold "Viewing artifact" header, video rendered in the same
  bounded cell area where images appear, same footer prompt with the same navigation keys once playback ends.
- During playback the user gets mpv's excellent terminal controls: `space` pause/resume, `←`/`→` seek, `m` mute toggle,
  `q` stop playback and return to the artifact prompt.
- Everything works in both launch modes the viewer already supports: the tracked tmux side pane and the non-tmux
  fullscreen fallback (TUI suspend).

## Current Understanding

The artifact preview pipeline is a chain with clean seams at every level:

- `action_open_agent_artifacts()` (in `src/sase/ace/tui/actions/agents/_panel_artifacts.py`) shows
  `AgentArtifactSelectionModal`, then calls `view_agent_artifact(s)_in_tmux_pane()` or, outside tmux, suspends the TUI
  and runs the viewer fullscreen.
- The tmux launcher (`src/sase/ace/tui/graphics/_viewer_tmux.py`) runs `tmux split-window -h` with
  `python -m sase.ace.tui.graphics.viewer --kind ... <paths>`, and the app tracks the pane (decoration, layout collapse,
  SIGUSR1 close notification, zoom).
- Inside the pane, `run_artifact_sequence_loop()` (`_viewer_loop.py`) picks a per-artifact view mode via
  `artifact_view_mode()` (`_viewer_render.py`): `image`/`pdf`/`markdown` render pages through `kitten icat` with a
  bounded `--place <cols>x<rows>@<left>x<top>` cell box computed by `artifact_image_area()`; `text` runs `bat`/`cat`. A
  single-key loop provides `j`/`k` pages, `n`/`p` artifacts, `r` refresh, `z` tmux zoom, `<tab>` focus SASE TUI, `q`
  quit.
- Image detection is suffix-based and ignores the stored artifact kind (`is_supported_image_path()`), which is exactly
  the pattern video needs: generated videos are persisted as kind `file` (per the generated-media default artifacts
  work), and `artifact_view_mode()` currently routes them to `text` mode.

mpv is the right playback engine because it renders video directly in the terminal via the kitty graphics protocol
(`--vo=kitty`) — the same protocol `kitten icat` already requires — and it supports cell-precise placement flags
(`--vo-kitty-cols/rows/left/top`) that map one-to-one onto the viewer's existing `ArtifactImageArea`. It also has
first-class terminal keybindings and a built-in terminal status line showing position/duration, so we get playback
controls and progress display for free.

The canonical video suffix set already exists: `SUPPORTED_VIDEO_EXTENSIONS` in `src/sase/axe/image_attachments.py`
(`.mp4`, `.m4v`, `.mov`, `.webm`), with a private `_is_supported_video_path()` helper. The TUI perf memory forbids
synchronous subprocess/disk work on the Textual event loop, so all video probing/playback must happen inside the viewer
subprocess — the TUI itself only does pure string suffix checks.

## Design

### One new view mode, not a new pane system

Add a `video` view mode to the existing artifact viewer rather than any parallel video-pane machinery. This inherits,
for free: pane lifecycle tracking, focus decoration, close notification, layout collapse, zoom-open, multi-artifact
sequences, marked-agent aggregation, and the non-tmux fullscreen fallback.

- `artifact_view_mode()` returns `"video"` when the path has a supported video suffix (checked before the generic
  `file`/`text` fallback, mirroring how image suffixes win regardless of kind).
- The artifact kind stays `file`. No new artifact kind, no index schema change, no Rust core change — the viewer is
  presentation-only, which keeps this cleanly on the Python side of the core-backend boundary.
- GIFs intentionally remain image-mode artifacts (kitty animates them via icat already); this is an explicit non-change.

### Suffix helper with a single source of truth

Expose a public `is_supported_video_path()` + `SUPPORTED_VIDEO_EXTENSIONS` from the graphics package (a small
`videos.py` sibling of `images.py`, exported through `graphics/__init__.py`). The suffix set must have one canonical
definition shared with `sase.axe.image_attachments` rather than a third copy — during implementation, pick the least
disruptive home (e.g. graphics/axe importing one shared constant) and update the existing private axe helper to reuse
it.

### Playback flow inside the sequence loop

In `run_artifact_sequence_loop()`, the `video` branch:

1. Clears the terminal and prints the same gold header panel, with a `▶ Video` metadata line (alongside the existing
   `Artifact i/N` line) so the surface reads as one family with the image viewer.
2. Computes the standard `artifact_image_area()` and launches mpv with the area mapped onto
   `--vo=kitty --vo-kitty-left/top/cols/rows`, so the video plays letterboxed in exactly the box images occupy. The
   cursor is positioned below the video area first so mpv's terminal status line (elapsed/duration) becomes the natural
   "progress bar" row, styled by mpv itself.
3. While mpv runs, mpv owns the keyboard: `space`, `←`/`→`, `m`, `q`. This is deliberate — reuse mpv's mature control
   loop during playback instead of multiplexing keys ourselves.
4. When mpv exits (user `q`, end of file, or error), the loop prints the standard footer prompt with the standard keys:
   `r` replays the video, `n`/`p` move between artifacts (mixing freely with images/PDFs), `z` toggles tmux zoom (replay
   then picks up the new pane size), `<tab>` focuses the SASE TUI, `q` quits the pane.
5. A nonzero mpv exit is surfaced exactly like `kitten icat` failures today: a warning (`mpv failed with exit code N`) —
   but the prompt stays alive so the user can still navigate to other artifacts.

Baseline mpv invocation (final flags tuned during implementation):

- `--no-config` so user mpv.conf files cannot break the curated terminal experience; customization goes through SASE
  config instead.
- `--vo=kitty` by default; the vo is configurable because terminal support varies (see Risks).
- `--mute=yes` by default: SASE typically runs on a remote host over SSH/tmux where the _server's_ audio device is
  useless; `m` unmutes for local sessions and a config key flips the default.
- `--keep-open=yes` so playback holds on the last frame instead of flash-clearing the pane at end of file.
- Quiet log levels, but keep mpv's terminal status line for position/duration feedback.

### Configuration

Add a small config block under the existing `ace:` section in `src/sase/default_config.yml` (exact key naming decided in
implementation, e.g. `ace.artifact_viewer.video`): `audio` (default off/muted), `loop` (default off), `vo` (default
`kitty`), and `extra_mpv_args` (default empty) for power users. Per the gotchas memory, the default config file must be
updated alongside the config plumbing. No new CLI subcommands or options are needed — the viewer module derives the mode
from the path.

### Dependency validation and doctor

- `validate_artifact_viewer_dependencies("video")` requires `mpv` (video mode does not need the `kitten` binary; mpv
  speaks the kitty protocol itself). Missing mpv produces the same friendly warning pattern as missing `kitten` does for
  images, including a hint to install mpv.
- Add an `mpv` row to `_OPTIONAL_TOOLS` in `src/sase/doctor/checks_tools.py` ("terminal video artifact playback") so
  `sase doctor` deep mode reports it.

### TUI polish (beautiful, and event-loop safe)

All TUI-side changes are pure string/suffix work — no subprocess or disk probing on the event loop (durations come from
mpv's own status line inside the viewer subprocess):

- **Artifact picker**: video-suffixed artifacts display a `[video]` tag (display-only override of the stored `file` kind
  in `_artifact_kind()`-level formatting) so users can tell videos apart at a glance.
- **Notification modal attachments**: video attachments currently fall into the "Could not read file" text path. Show a
  styled placeholder card instead (file name, size, and a `▶ video — press the view key to play` hint), and generalize
  the existing view-image action + `view_image_file()` call to route through `view_artifact_file()` so the same key that
  opens image attachments plays video attachments.
- **File panel**: give video files the same placeholder treatment instead of attempting a text read.

### Documentation

- Extend `docs/agent_images.md` (which now documents generated media default artifacts) with a "Video preview" section:
  controls, mute default, config keys, and the mpv dependency.
- Audit the `?` help popup per the ace guidelines; the `a` keymap's behavior description likely needs no change (same
  action, richer artifact support), but update it if it mentions images only.

## Implementation Steps

1. **Verify mpv terminal playback in the target environment first.** Before writing code, confirm `mpv --vo=kitty`
   renders inside a tmux pane in kitty (graphics passthrough), and record working flags. If kitty-vo-in-tmux proves
   unreliable, select the best default (`sixel`/`tct` fallback order) and shape the `vo` config default accordingly.
   This spike de-risks the whole feature and takes minutes.

2. **Add the video suffix helper.** New `src/sase/ace/tui/graphics/videos.py` with `SUPPORTED_VIDEO_EXTENSIONS` /
   `is_supported_video_path()`, exported from `graphics/__init__.py`, sharing one canonical suffix constant with
   `sase/axe/image_attachments.py`.

3. **Teach the renderer the `video` mode.** Extend `ArtifactViewMode` and `artifact_view_mode()` in `_viewer_render.py`
   (suffix check ahead of the text fallback; honor an explicit `video` kind string for future-proofing), and extend
   `validate_artifact_viewer_dependencies()` to require mpv for video mode. `render_artifact_pages()` returns a no-pages
   result for video (like text mode) since playback bypasses page rendering.

4. **Implement playback in the viewer loop.** Add an mpv command builder (area→placement flag mapping, defaults, config
   overrides) plus the `video` branch in `run_artifact_sequence_loop()` in `_viewer_loop.py`: header with `▶ Video`
   metadata, mpv subprocess, post-playback footer prompt with `r`/`n`/`p`/`z`/`<tab>`/`q`, warning-not-fatal error
   handling. Keep everything injectable (`run_command`, `read_key`) so tests never launch real mpv.

5. **Wire configuration.** Config plumbing for audio/loop/vo/extra args, with `src/sase/default_config.yml` updated and
   the values threaded into the mpv command builder (the viewer subprocess loads config the same way other viewer
   settings are resolved, or receives flags via the module command if that is the established pattern).

6. **Polish the TUI surfaces.** Picker `[video]` display tag in `agent_artifacts_modal.py`; notification modal video
   placeholder + play action generalization in `notification_modal_attachments.py`; file panel video placeholder in
   `file_panel/_display.py`.

7. **Add the doctor check.** `mpv` optional-tool row in `checks_tools.py`.

8. **Tests and docs.** Per the Tests section below, plus the `docs/agent_images.md` video preview section and help popup
   audit.

## Expected Non-Changes

- No new artifact kind: videos stay kind `file`; detection is suffix-based like images.
- No artifact index schema, `done.json`, or notification schema changes.
- No Rust core (`sase-core`) changes: the artifact viewer is presentation-only Python by the core-backend boundary rule.
- No new CLI subcommands or CLI options.
- No new TUI keymaps: `open_agent_artifacts` (`a`) and the existing notification-modal view action cover everything;
  playback keys live inside mpv/the viewer pane.
- No Telegram plugin changes.
- GIF behavior is unchanged (image mode, animated by kitty icat).

## Tests

Focused tests first (all viewer tests use the existing injectable `run_command`/`read_key` fakes — never real mpv):

- `artifact_view_mode()`: video suffixes → `video` for kind `file`/`None`; image suffixes still win as images; text
  fallback intact.
- `is_supported_video_path()` and suffix-set consistency with the axe attachment constants (single-source assertion).
- `validate_artifact_viewer_dependencies("video")`: missing-mpv warning shape.
- mpv command builder: placement mapping from `ArtifactImageArea`, mute/loop/vo defaults, config overrides,
  `--no-config` presence.
- Sequence loop video branch: header printed, mpv command executed, `r` replays, `n`/`p` navigate mixed image+video
  sequences, `q` quits, nonzero mpv exit yields warning + live prompt.
- Picker: video artifact rows render the `[video]` tag (and PNG visual snapshots via `just test-visual` if the picker is
  covered there; accept intentional golden updates only).
- Notification modal: video attachment renders the placeholder and the view action routes to the artifact viewer.
- Doctor: optional-tools check includes the mpv row.

Then the project-required gate:

- `just install`
- `just check`

## Risks and Mitigations

- **mpv kitty-vo under tmux passthrough is the main unknown.** `kitten icat` handles tmux passthrough itself; mpv's
  kitty vo support varies by version/terminal. Mitigation: implementation step 1 verifies real behavior up front, the vo
  is configurable, and `tct` (plain truecolor cells, works in effectively any terminal) is the documented last-resort
  fallback.
- **Remote/SSH playback bandwidth.** Kitty-protocol frames over SSH can drop frame rate; mpv's default framedropping
  keeps A/V time correct, and the feature remains useful (previewing generated clips, not cinema). Documented as a known
  limitation.
- **Audio device absence on headless servers.** Muted by default; mpv continues video-only if audio init fails, so this
  cannot break playback.
- **User mpv configs breaking the experience.** `--no-config` isolates the viewer; customization flows through SASE
  config (`extra_mpv_args`).
- **TUI responsiveness.** All new TUI-side logic is suffix string checks; playback and any metadata display live in the
  viewer subprocess, per the TUI perf rules (no event-loop subprocess/disk work).
- **Codec coverage.** mpv/ffmpeg decode the supported container set (`.mp4`, `.m4v`, `.mov`, `.webm`) broadly; a decode
  failure surfaces as the standard viewer warning rather than a crash.

## Acceptance Criteria

- From the Agents tab, choosing a generated `.mp4` artifact in the picker opens the right-side artifact pane and plays
  the video in-terminal, bounded to the same area images use, under the standard artifact header.
- `space`/`←`/`→`/`m` work during playback; `q` ends playback into the artifact footer prompt where `r` replays and
  `n`/`p`/`z`/`<tab>`/`q` behave exactly as they do for images; mixed image+video multi-artifact opens navigate
  seamlessly.
- Outside tmux, opening a video suspends the TUI and plays fullscreen, matching image behavior.
- With mpv missing, opening a video shows a friendly warning naming mpv (no crash, no binary text dump), and
  `sase doctor` deep mode reports the missing optional tool.
- Videos are muted by default with `m` available to unmute; config can enable audio, looping, a different vo, and extra
  mpv args.
- Video rows are visually identifiable in the artifact picker, notification-modal video attachments show a playable
  placeholder instead of a read error, and no TUI event-loop path gained subprocess or disk probing.
