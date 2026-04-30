# Agent Image Attachments and TUI Graphics

## Overview

SASE treats image files produced by agents as first-class completion artifacts. When a successful agent adds or modifies
a supported image file, the completion path records the image in `done.json` and appends it to the notification file
list after the standard chat and diff artifacts. Notification plugins can then deliver those image files without
re-scanning the workspace.

Supported image extensions are:

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`
- `.gif`

## Completion Attachment Contract

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

## Notification Delivery

Core SASE stores image attachments in the existing `Notification.files` list. There is no separate notification schema
field for typed attachments yet. This keeps the contract compatible with existing notification storage and lets
downstream plugins decide how to render each file:

- Telegram integrations can send images as photos and keep markdown/diff files as documents.
- Google Chat integrations can upload image files directly into the completion thread.
- The ACE notification modal can still open attached files in `$EDITOR` with `e` and cycle them with `Ctrl+N` /
  `Ctrl+P`.

See [`notifications.md`](notifications.md) for the notification model and modal keybindings.

## ACE Terminal Graphics Foundation

ACE now probes terminal graphics support before the Textual app starts and stores the detected capability on `AceApp`.
The notification modal and Agents tab file panel route supported image extensions through the preview layer before
attempting text decoding.

Capability detection is conservative:

- known Kitty-placeholder-capable terminal families are considered (`kitty` and `ghostty`)
- truecolor support is required
- tmux sessions use Kitty passthrough wrapping
- an active Kitty graphics probe must succeed unless the caller explicitly skips probing

The internal preview renderable currently transmits PNG bytes through the Kitty graphics protocol and falls back to a
text placeholder for unsupported terminals, missing files, unsupported extensions, and non-PNG raster files. JPEG, WebP,
and GIF are collected as notification attachments today, but need a future transcoding/display step before inline Kitty
preview can render them. The fallback includes the file path, byte size when available, and the relevant editor action
(`e` in notifications or `%E` in agent panels) so non-Kitty sessions remain usable.

Set `SASE_TUI_GRAPHICS=off` (also accepts `0`, `false`, `no`, `disable`, or `disabled`) to disable terminal graphics
detection. Set it to `kitty` (also accepts `1`, `true`, `yes`, `on`, or `force`) to bypass the known-terminal-family
gate while still requiring truecolor and a successful active probe.

Source: `src/sase/ace/tui/graphics/`
