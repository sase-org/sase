# Agent Attachments and TUI Graphics

## Overview

SASE treats files produced by agents as first-class completion artifacts. When a successful agent adds or modifies a
supported image file, the completion path records the image in `done.json` and appends it to the notification file list
after the standard chat and diff artifacts. When a successful agent adds or modifies Markdown, core SASE renders a PDF
artifact and attaches that PDF to the same completion notification. Notification plugins can then deliver those files
without re-scanning the workspace.

Supported image extensions are:

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`
- `.gif`

## Image Attachment Contract

Image discovery runs when an agent finalizes successfully. The collector checks candidate paths in stable order:

1. tracked files changed relative to `HEAD`
2. untracked files in the agent workspace
3. files named by the saved proposal or commit diff
4. files touched by the latest commit when the agent committed or opened a PR

Only existing files with supported image extensions are kept. Paths are resolved to absolute paths so outbound
notification processes can attach them even when they run outside the agent workspace. Duplicates are removed while
preserving order, and image paths are appended after any already-attached chat or diff files.

The same list is persisted as `image_paths` in the agent's `done.json`. Agent metadata consumers should read that field
instead of trying to infer generated images from arbitrary notification files.

Source: `src/sase/axe/image_attachments.py`

## Markdown PDF Attachment Contract

Markdown discovery runs on successful agent finalization with the same candidate ordering as image discovery. Supported
source extensions are `.md` and `.markdown`. Sources are resolved to existing workspace files, generated run artifacts
are excluded, and duplicates are removed before rendering.

Core SASE renders discovered Markdown sources into the current agent artifacts directory:

```text
<artifacts_dir>/markdown_pdfs/<sanitized-relative-source-path>.pdf
<artifacts_dir>/markdown_pdfs/index.json
```

Rendering is best-effort. Missing Pandoc/PDF-engine tools or conversion errors do not fail the agent run; failed sources
are omitted. Successful PDF paths are persisted as `markdown_pdf_paths` in `done.json`, and `index.json` records
`source_path` to `pdf_path` mappings for diagnostics.

Completion notifications attach generated Markdown PDFs after the saved chat and diff files, before image attachments.
The Agents tab file panel also loads `markdown_pdf_paths` alongside plan and image files for completed agents.

Sources:

- `src/sase/attachments/markdown_pdf.py`
- `src/sase/axe/run_agent_exec.py`

## Notification Delivery

Core SASE stores generated PDFs and image attachments in the existing `Notification.files` list. There is no separate
notification schema field for typed attachments yet. This keeps the contract compatible with existing notification
storage and lets downstream plugins decide how to render each file:

- Telegram integrations can send images as photos and keep markdown/diff files as documents.
- Google Chat integrations can upload image files directly into the completion thread.
- The ACE notification modal can still open attached files in `$EDITOR` with `e` and cycle them with `Ctrl+N` /
  `Ctrl+P`.

See [`notifications.md`](notifications.md) for the notification model and modal keybindings.

## ACE Terminal Graphics Foundation

ACE now probes terminal graphics support before the Textual app starts and stores the detected capability on `AceApp`.
The notification modal and Agents tab file panel route supported image extensions through the preview layer before
attempting text decoding.

Capability detection is conservative for generic terminals, but it can use an active Kitty probe to prove support:

- known Kitty-placeholder-capable terminal families are considered (`kitty` and `ghostty`)
- tmux sessions use Kitty passthrough wrapping and may probe even when tmux hides the outer terminal family
- force mode bypasses the known-terminal-family gate
- an active Kitty graphics probe must succeed unless the caller explicitly skips probing
- truecolor advertisement is recorded for diagnostics and placeholder rendering, but missing `COLORTERM=truecolor` does
  not block a successful active probe in tmux or force mode

The internal preview renderable currently transmits PNG bytes through the Kitty graphics protocol and falls back to a
text placeholder for unsupported terminals, missing files, unsupported extensions, and non-PNG raster files. JPEG, WebP,
and GIF are collected as notification attachments today, but need a future transcoding/display step before inline Kitty
preview can render them. The fallback includes the file path, byte size when available, and the relevant editor action
(`e` in notifications or `%E` in agent panels) so non-Kitty sessions remain usable.

Set `SASE_TUI_GRAPHICS=off` (also accepts `0`, `false`, `no`, `disable`, or `disabled`) to disable terminal graphics
detection. Set it to `kitty` (also accepts `1`, `true`, `yes`, `on`, or `force`) to bypass the known-terminal-family
gate while still requiring a successful active probe.

Source: `src/sase/ace/tui/graphics/`
