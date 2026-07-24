# Agent Attachments and Image Previews

## Overview

SASE treats files produced by agents as first-class completion artifacts. When a successful agent adds or modifies a
supported image or video file, the completion path records the media in `done.json` and appends it to the notification
file list after the standard chat and diff artifacts, and after any generated Markdown PDFs. When a successful agent
adds or modifies up to 10 Markdown files, core SASE renders PDF artifacts and attaches those PDFs to the same completion
notification. Explicit artifacts saved with `sase artifact create` are appended after generated media when the agent
completion notification is sent. Notification plugins can then deliver those files from `Notification.files` without
re-scanning the workspace.

ACE is SASE's terminal UI. It has two image surfaces: lightweight in-panel previews for notification and file-panel
attachments, and the separate `a` artifact viewer for opening completed agent artifacts.

ACE can also surface media files referenced in saved prompt artifacts (`raw_xprompt.md` and `*_prompt.md`) even when the
media itself was not part of the agent's git diff. For current successful runs, those prompt-referenced media files are
copied into persistent SASE artifact storage with the other default generated-media artifacts so the Agents-tab artifact
picker can still open them after a workspace is cleaned up. Legacy runs without persisted default artifacts fall back to
prompt-file discovery at view time. Prompt-referenced media are not notification delivery attachments unless they also
appear in `done.json.image_paths`, appear in `done.json.video_paths`, or were saved explicitly with
`sase artifact create`.

Supported image extensions are:

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`
- `.gif`

Supported video extensions are:

- `.mp4`
- `.m4v`
- `.mov`
- `.webm`

## Generated Media Attachment Contract

Generated-image discovery runs when an agent finalizes successfully. This contract covers images added to
`done.json.image_paths` and completion notifications. Generated-video discovery uses the same algorithm and writes
videos to `done.json.video_paths`. The collector checks candidate paths in stable order:

1. tracked files changed relative to `HEAD`
2. untracked files in the agent workspace
3. files named by the saved proposal or commit diff
4. files touched by the latest commit when the agent committed or opened a PR

Only existing files with supported media extensions are kept. Paths are resolved to absolute paths so outbound
notification processes can attach them even when they run outside the agent workspace. Duplicates are removed while
preserving order. Generated images are appended after any already-attached chat, diff, or generated PDF files; generated
videos are appended after generated images.

The same lists are persisted as `image_paths` and `video_paths` in the agent's `done.json`. Agent metadata consumers
should read those fields instead of trying to infer generated media from arbitrary notification files. GIFs remain in
`image_paths` for compatibility with image-preview consumers; downstream notification plugins can still choose an
animation-specific transport based on the `.gif` suffix.

Source: `src/sase/axe/image_attachments.py`

### Prompt-Referenced Media Default Artifacts

Default artifact persistence also scans the saved prompt files in the agent artifacts directory:

- `raw_xprompt.md`
- every sibling `*_prompt.md` file

Any path-like token ending in a common image suffix or supported video suffix is resolved as an absolute, home-relative,
or workspace-relative path. Existing files are added after `done.json.image_paths` and `done.json.video_paths`,
duplicates are removed, and the file does not need to appear in the agent's git diff. Images and GIFs are added as
`image` artifacts. Prompt-referenced videos are added as ordinary `file` artifacts; ACE detects the video suffix at view
time and opens them with the video preview path.

This is useful when a prompt asks an agent to inspect or transform an existing screenshot, mockup, reference image, or
reference video and the resulting run should keep that source media one keypress away in ACE.

Prompt-referenced media are ACE artifact-list entries, not notification delivery attachments. Current runs persist them
to the global artifact index during finalization; legacy runs can still synthesize them from prompt artifacts when ACE
loads the row. Downstream notification plugins should continue to use `done.json.image_paths` and
`done.json.video_paths` for the generated-media notification contract.

Source: `src/sase/core/agent_artifact_defaults.py`

## Markdown PDF Attachment Contract

Markdown discovery runs on successful agent finalization with the same candidate ordering as image discovery. Supported
source extensions are `.md` and `.markdown`. Sources are resolved to existing workspace files, generated run artifacts
are excluded, and duplicates are removed before rendering. If more than 10 Markdown sources remain after filtering, SASE
skips PDF rendering for that run and adds a completion-notification note instead of rendering a large attachment set.

Core SASE renders discovered Markdown sources into the current agent artifacts directory:

```text
<artifacts_dir>/markdown_pdfs/<sanitized-relative-source-path>.pdf
<artifacts_dir>/markdown_pdfs/index.json
```

Rendering is best-effort. Missing Pandoc/PDF-engine tools or conversion errors do not fail the agent run; failed sources
are omitted. Successful PDF paths are persisted as `markdown_pdf_paths` in `done.json`, and `index.json` records
`source_path` to `pdf_path` mappings for diagnostics. When the 10-source limit is exceeded,
`done.json.markdown_pdf_paths` is empty and the source count is carried through completion handling for the user-facing
skip note.

While PDFs are being prepared, the runner writes `workflow_state.json.pdf_status` plus a compact `activity` label. ACE
loads those fields during refresh and shows messages such as `Preparing PDFs from Markdown...`, `PDF 2/4 <path>`, or
`PDFs done 3/4 (1 skipped)` on the Agents row and in the agent header. This status is transient finalization state; the
durable output remains `done.json.markdown_pdf_paths` and `markdown_pdfs/index.json`.

Markdown PDFs use a built-in small-screen layout by default: a narrow portrait page, small margins, larger readable body
text, and wrapping-friendly CSS for code blocks, tables, links, and other long content. The preferred `wkhtmltopdf` path
receives both the default stylesheet and explicit page/margin options; LaTeX fallbacks receive the same page size,
margin, font size, and line-height defaults through Pandoc variables.

When a discovered Markdown source starts with usable, non-empty YAML frontmatter, the generated PDF replaces the raw
metadata block with a styled **Properties** card and uses its string `title` as the PDF document title. Property
ordering and nested-value formatting match ACE's plan-detail presentation; HTML-sensitive property text is escaped.
Empty, malformed, or absent frontmatter leaves the source unchanged, and a preprocessing failure falls back to rendering
the original Markdown. Dedicated launch-preview PDFs opt out of this transformation so prompt frontmatter and
highlighting retain their launch-review presentation.

Completion notifications attach generated Markdown PDFs after the saved chat and diff files, before image attachments.
The Agents tab file panel also loads `markdown_pdf_paths` alongside plan and image files for completed agents.

Sources:

- `src/sase/attachments/markdown_pdf.py`
- `src/sase/axe/run_agent_exec.py`

## Explicit Artifact Contract

Agents can save a generated file explicitly with:

```bash
sase artifact create -p <path> [-n <label>] [-k <kind>]
```

The CLI command is intended for agent processes: it requires `SASE_AGENT=1` and `SASE_ARTIFACTS_DIR` so SASE knows which
run owns the artifact. It moves the source file into persistent SASE artifact storage, records an association with the
current agent, and lets ACE show the artifact even after the agent is dismissed and later revived. During completion
notification delivery, SASE appends existing explicit artifact files after chat, diff, generated Markdown PDFs,
generated image attachments, and generated video attachments. Duplicate paths and missing files are ignored, and
explicit-artifact index failures do not fail the completion path.

Source: `src/sase/core/agent_artifact_facade.py`

## Notification Delivery

Core SASE stores generated PDFs, generated images, generated videos, and explicit artifact attachments in the existing
`Notification.files` list. There is no separate notification schema field for typed attachments yet. This keeps the
contract compatible with existing notification storage and lets downstream plugins decide how to render each file:

- Telegram integrations can send static images as photos, GIFs as animations, videos as videos, and keep markdown/diff
  files as documents.
- Google Chat integrations can upload image files directly into the completion thread.
- The ACE notification modal can still open attached files in `$EDITOR` with `e` and cycle them with `Ctrl+N` /
  `Ctrl+P`.

See [`notifications.md`](notifications.md) for the notification model and modal keybindings.

## ACE Artifact Viewer

The Agents tab exposes completed agent artifacts through the `a` key. When artifacts exist, ACE opens the artifact panel
for selection. Chat transcripts, plan files, generated Markdown PDFs, generated images, generated videos,
prompt-referenced media, and explicit artifacts created with `sase artifact create -p <path> [-n <label>] [-k <kind>]`
all use the same list. Generated videos are stored as ordinary `file` artifacts, but the picker labels supported video
suffixes as `[video]` and the viewer opens them with terminal video playback. The panel is shown even for a single
artifact so users can confirm the artifact label, kind, and path before opening it.

The selected agent's prompt/detail header also includes non-chat artifacts in the plan-adjacent `SASE CONTEXT`
`ARTIFACTS` lane. The complete lane order is `PLAN`, `ARTIFACTS`, `MEMORY`, `SKILLS`, then `WORKSPACES`; within
`ARTIFACTS`, `Commits`, `Deltas`, and `Artifacts` remain in that order when present. Paths are shown relative to the
agent workspace when possible, home-relative when appropriate, and with hint numbers when hint mode is active.

The panel supports one-key selectors, `j`/`k` navigation, `m` to mark rows, `Enter` to open the marked set or
highlighted row, `y` to copy highlighted Markdown contents, `Y` to copy the highlighted artifact path, and `A` to open
every artifact in list order. Copied paths are workspace-relative when possible and fall back to home-relative paths.
When multiple artifacts are opened together, the terminal viewer adds `n`/`p` navigation between artifacts in addition
to page navigation.

When ACE is running inside tmux, the artifact viewer launches in a right-side tmux pane and the Agents list collapses
while the pane is live. Press `l` from the Agents tab to focus the tracked artifact pane, or press `a` again to close
it. Row-changing navigation is guarded while the pane is open so the TUI does not drift to a different agent than the
viewer. Outside tmux, ACE suspends and opens the viewer in the current terminal pane. The viewer chooses its mode from
the artifact kind and file extension: supported images are displayed directly, supported videos play with mpv, PDFs are
converted to PNG pages, and Markdown is rendered to PDF before paging. The page loop uses `j`/`k` to move between pages,
wrapping at the first and last page, `n`/`p` to move between artifacts in a sequence, `r` to refresh or replay the
current artifact, and `q` to close the viewer.

Only one plan artifact is listed for each agent. If run metadata contains both an archived plan path and an SDD tale
path, committed plans prefer the SDD path; uncommitted plans prefer the archived path unless only the SDD path is
available.

Viewer dependencies are intentionally outside the agent completion path. `kitten` is required for image/PDF/Markdown
terminal display, `mpv` is required for terminal video playback, `pdftoppm` is required for PDF/Markdown paging, and
Markdown rendering also needs `pandoc` plus one supported PDF engine. If a dependency is missing, ACE shows a warning
instead of failing the TUI or changing the stored artifact list.

Source: `src/sase/ace/tui/graphics/viewer.py`

### Video Preview

ACE plays `.mp4`, `.m4v`, `.mov`, and `.webm` artifacts in the same artifact viewer used for images and PDFs. Inside
tmux, selecting a video opens the tracked right-side artifact pane; outside tmux, ACE suspends and plays in the current
terminal. Playback uses `mpv --vo=kitty` by default, bounded to the same cell area used for image artifacts.

While mpv is running, mpv owns playback keys: `space` pauses or resumes, arrow keys seek, `m` toggles mute, and `q`
stops playback. After playback exits, the artifact viewer footer returns with the usual navigation keys: `r` replays,
`n`/`p` move through a multi-artifact sequence, `z` toggles tmux zoom when available, `<tab>` focuses the SASE TUI from
a tmux artifact pane, and `q` closes the viewer.

Videos are muted by default because SASE often runs on a remote host or inside tmux where the server audio device is not
useful. Configure playback under `ace.artifact_viewer.video`:

```yaml
ace:
  artifact_viewer:
    video:
      audio: false
      loop: false
      vo: "kitty"
      extra_mpv_args: []
```

Set `audio: true` to start unmuted, `loop: true` to pass `--loop-file=inf`, `vo` to use another mpv video output such as
`tct`, and `extra_mpv_args` to append additional mpv flags after SASE defaults. SASE launches mpv with `--no-config` so
user mpv profiles cannot break the curated terminal preview; put viewer-specific customization in the SASE config
instead.

## ACE Image Preview Foundation

The notification modal and Agents tab file panel route supported image extensions through the preview layer before
attempting text decoding.

The internal preview layer renders PNG, JPEG, WebP, and GIF attachments as a portable Rich cell preview. It uses Pillow
to decode the first image frame, apply EXIF orientation, fit it inside the visible panel bounds, composite transparency
onto a dark background, and apply a mild preview-only sharpen pass after resizing. Each terminal cell samples a 2 x 2
pixel block and chooses the closest Unicode block mask with foreground and background colors, which preserves more
edges, diagonals, UI details, and text-like shapes than a fixed half-block sampler.

No Kitty, iTerm2, Sixel, or other terminal image protocol support is required. The renderer only emits colored Unicode
text through Rich/Textual, so it works the same way in ordinary terminals, multiplexed sessions, SSH sessions, and
environments with no image protocol support. Preview quality depends on the visible pane size and terminal color depth:
larger panes provide more sampled cells, and truecolor terminals preserve colors better than 256-color terminals.

ACE checks only terminal color depth from the environment. When `COLORTERM=truecolor`, `COLORTERM=24bit`, or a truecolor
marker in `TERM` is present, previews use 24-bit color; otherwise they use 256-color approximations. Missing files,
unsupported extensions, decode errors, missing Pillow, and images above the renderer guardrails show a concise text
fallback with the file path, byte size when available, and the relevant editor or artifact action. Use `e` in
notifications, `E` on the Agents tab, or the `a` artifact viewer whenever full-fidelity viewing is needed.

Source: `src/sase/ace/tui/graphics/`
