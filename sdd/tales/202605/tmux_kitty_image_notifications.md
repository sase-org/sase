---
create_time: 2026-05-07 10:40:04
status: done
prompt: sdd/prompts/202605/tmux_kitty_image_notifications.md
---
# Fix Blurry Notification Image Previews in tmux

## Problem

Image attachments can appear as unrecognizable colored blobs in the notification modal. The specific failing fixture is
`/home/bryan/projects/github/sase-org/sase_102/docs/images/xprompt-resolution-infographic.png`, a 1672x941 PNG with text
and diagram detail.

The notification payload and store are correct: the notification points at the PNG, and `sase notify show` returns the
expected file attachment. The problem is in the TUI preview path.

## Root Cause

The TUI has two image preview modes:

- Native Kitty graphics for PNGs, which uploads the original PNG and lets the terminal scale it.
- A portable Rich cell fallback, which downsamples the image to terminal cells using half-block characters.

In the current session, `sase ace` runs inside tmux with:

- `TERM=tmux-256color`
- `TERM_PROGRAM=tmux`
- `TMUX=...`

The SASE graphics detector sees only that inner tmux environment. Because the terminal family is unknown and default
active probes are intentionally disabled, it returns `GraphicsCapability(supported=False, passthrough="tmux")`.

tmux itself knows the outer client is Kitty:

- `tmux display-message -p '#{client_termname}'` returns `xterm-kitty`
- `tmux show-environment -g TERM` returns `xterm-kitty`
- `tmux show -g allow-passthrough` returns `allow-passthrough all`

SASE does not currently consult this tmux metadata, so it incorrectly falls back to the cell renderer. For a detailed
1672x941 infographic, the fallback is effectively compressing the image to at most about 80x48 pixels of color samples,
which destroys the text and produces the blob-like preview.

## Plan

1. Extend graphics capability detection to understand tmux outer-terminal metadata without reintroducing unsolicited
   terminal probes.
   - Add a small tmux metadata helper in `src/sase/ace/tui/graphics/capability.py`.
   - When `TMUX` is present and the normal environment does not identify a known terminal, query tmux with short,
     non-shell subprocess calls:
     - `tmux display-message -p '#{client_termname}'`
     - fallback: `tmux show-environment -g TERM`
     - `tmux show -gqv allow-passthrough`
   - Treat Kitty/Ghostty outer terminal names the same way direct `TERM`/`TERM_PROGRAM` detection is treated today.

2. Gate automatic native graphics inside tmux on passthrough support.
   - If the outer terminal is Kitty/Ghostty and tmux `allow-passthrough` is enabled (`on`, `all`, or compatible value),
     return a supported Kitty graphics capability with `passthrough="tmux"`.
   - If the outer terminal is Kitty/Ghostty but passthrough is disabled or unavailable, keep graphics unsupported with a
     clear reason instead of emitting placeholder cells that the terminal cannot replace.
   - Preserve existing `SASE_TUI_GRAPHICS=kitty` force behavior.

3. Broaden terminal-family parsing enough to cover tmux-discovered values.
   - Recognize `xterm-kitty` and Kitty env values as Kitty.
   - Recognize Ghostty via `TERM_PROGRAM=ghostty`, `GHOSTTY_RESOURCES_DIR`, and likely `TERM` strings containing
     `ghostty`.
   - Avoid broad guesses for generic terminals.

4. Add focused tests in `tests/ace/tui/graphics/test_capability.py`.
   - tmux + `client_termname=xterm-kitty` + passthrough enabled returns supported Kitty capability with
     `passthrough="tmux"`.
   - tmux + outer Kitty + passthrough disabled remains unsupported with an explanatory reason.
   - tmux metadata command failures fall back to the existing unsupported/no-probe result.
   - unknown tmux terminal still does not actively probe by default.
   - direct known terminal behavior and forced-probe behavior continue to pass.

5. Validate the preview selection path.
   - Add or update a renderable-level test showing that a tmux-supported Kitty capability makes
     `image_preview(...png...)` return `KittyImageRenderable`, not `CellImageRenderable`.
   - Keep existing cell fallback behavior for unsupported terminals and non-PNG image formats.

6. Run verification.
   - Run the targeted graphics tests first.
   - Run the existing image panel/notification modal tests.
   - Run `just install` if the workspace environment needs refresh, then `just check` per repo instructions after code
     changes.

## Expected Outcome

In this tmux-on-Kitty setup, `sase ace` should detect native graphics support automatically and render PNG notification
attachments through `KittyImageRenderable` with tmux passthrough. The notification image should be recognizable because
the terminal receives the original PNG instead of the low-resolution cell fallback.

Users without Kitty/Ghostty graphics or without tmux passthrough still get the portable fallback or a clear unavailable
reason, and startup remains side-effect-free by default.
