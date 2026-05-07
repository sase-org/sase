---
create_time: 2026-05-07 16:54:09
status: done
prompt: sdd/prompts/202605/high_quality_notification_images.md
---
# High-Quality Notification Image Previews

## Goal

Make image attachments in the ACE notification modal look substantially better while keeping the preview path portable.
The implementation should continue to use Pillow plus Rich/Textual terminal rendering and must not introduce terminal
protocol branches such as Kitty, iTerm2, Sixel, or any emulator-specific escape sequence.

## Current Behavior

Image attachment display flows through:

- `src/sase/ace/tui/modals/notification_modal_attachments.py`
- `src/sase/ace/tui/graphics/renderable.py`
- `src/sase/ace/tui/graphics/cell.py`
- `src/sase/ace/tui/graphics/sizing.py`
- `src/sase/ace/tui/styles.tcss`

The current renderer decodes the first image frame with Pillow, fits it into the visible pane, and emits one Rich
segment per terminal cell using an upper-half block with foreground/background colors. This is portable, but the
effective image resolution is tiny:

- width is one sampled pixel per terminal column
- height is two sampled pixels per terminal row
- preview size is capped at `80 x 24` terminal cells
- the notification modal gives only 60% of the modal width to the preview pane

That means a fairly large terminal often previews a generated image at roughly `80 x 48` sampled pixels, and smaller
terminals get less. For screenshots, UI mockups, diagrams, generated infographics, and images with text, this is
expected to look blocky and low quality even when Pillow and truecolor work correctly.

## Design

### 1. Keep the renderer terminal-agnostic

Do not add image protocol detection or terminal-specific branches. The quality work should stay inside the existing
portable rendering layer:

- Pillow for decode, orientation, resize, compositing, and optional enhancement
- Rich `Segment` output for colored Unicode block glyphs
- existing generic truecolor/256-color context
- existing text fallback behavior

This keeps previews working over SSH, tmux, ordinary terminal emulators, and environments that do not support terminal
image protocols.

### 2. Replace the fixed half-block sampler with an adaptive block-mask renderer

Update `CellImageRenderable` so each terminal cell represents a `2 x 2` source sample instead of a `1 x 2` sample. For
every terminal cell:

1. resize the fitted image to `columns * 2` by `rows * 2` pixels
2. inspect the four subpixels for that cell
3. evaluate a small table of Unicode block masks: space, full block, upper/lower half, left/right half, quadrants,
   diagonals, and three-quarter blocks
4. choose foreground/background colors and the glyph mask with the lowest color error
5. emit one Rich segment with that glyph and the chosen foreground/background colors

This increases spatial detail without increasing the number of terminal cells. It is still just Unicode text with ANSI
color, but it can preserve edges, diagonals, icons, small UI details, and text-like shapes much better than always using
an upper-half block.

The existing upper-half behavior should become one candidate in the mask table, not a separate terminal-specific mode.

### 3. Improve image preprocessing before cell conversion

While touching the render pipeline, add generic Pillow quality improvements:

- apply EXIF orientation with `ImageOps.exif_transpose`
- composite transparency after resizing onto the existing dark preview background
- use LANCZOS for downsampling
- apply a mild, bounded sharpen pass after resize so small text, borders, and generated-image details survive terminal
  rasterization better

The sharpen pass should be conservative and deterministic. It should not alter the file, only the preview buffer.

### 4. Use more of the notification modal for images

Improve preview dimensions without making the modal awkward for text notifications:

- raise the generic preview caps in `sizing.py` so large terminals are not artificially limited to `80 x 24`
- consider caps around `120-160` columns and `40-60` rows, bounded by measured viewport size
- make the notification modal image-aware by adding a class when the current attachment is an image
- when image-aware, shift panel width toward the preview pane, for example left list `30%` and right preview `70%`
- keep existing list layout for non-image attachments

The modal should still fit within the existing `95% x 90%` container and rely on the current scroll pane for overflow.

### 5. Keep performance bounded

The higher-quality renderer should preserve the existing guardrails and cache strategy:

- keep file-size and decoded-pixel limits
- keep cache keys based on path, file metadata, dimensions, color mode, and background
- avoid work proportional to original image size after Pillow has resized to preview dimensions
- keep segment count equal to `columns * rows`

If needed, cap notification previews more tightly than agent file-panel previews, but use the same renderer in both
surfaces so behavior stays consistent.

### 6. Tests

Add focused tests around the rendering algorithm and modal sizing:

- solid-color images still render stable dimensions and low segment count
- checkerboard or diagonal `2 x 2` fixtures select non-half-block masks
- transparency composites against the configured background
- EXIF orientation is respected where Pillow can generate the fixture cheaply
- truecolor and 256-color paths both emit valid Rich styles
- notification image mode asks for the wider/larger preview dimensions
- existing fallback behavior remains unchanged for missing, unsupported, broken, and oversized images

Avoid brittle golden snapshots of full ANSI output. Assert dimensions, glyph class, style presence, and selected
behavior.

### 7. Documentation

Update `docs/agent_images.md` to describe the improved portable renderer accurately:

- no terminal image protocol support is required
- previews use Pillow-backed adaptive Unicode block rendering
- quality depends on pane size and terminal color depth
- `e` in notifications and `%E` in agent panels remain the escape hatch for full-fidelity viewing

## Validation

After implementation:

1. run focused tests for graphics and notification image panels
2. run `just check` from this workspace, after `just install` if the environment has not been prepared
3. manually inspect at least one generated image notification in `sase ace` on a normal terminal with no Kitty-specific
   assumptions

## Non-Goals

- no Kitty graphics protocol
- no iTerm2 inline images
- no Sixel probing
- no terminal-emulator allowlist
- no persistent preview image files
- no change to the notification storage schema
