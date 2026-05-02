---
create_time: 2026-04-30 11:08:29
status: done
prompt: sdd/prompts/202604/kitty_image_panel_fix.md
---
# Fix Kitty Image Rendering In File And Notification Panels

## Context

ACE already has a terminal graphics foundation:

- `detect_graphics_capability()` probes Kitty support before Textual starts and records `GraphicsCapability` on
  `AceApp`.
- The Agents tab file panel and notification modal route supported image paths through `image_preview(...)`.
- `KittyImageRenderable` uploads PNG bytes with Kitty graphics protocol escape sequences, creates a virtual placement,
  and prints a Unicode placeholder grid for that placement.

The affected surfaces are:

- `src/sase/ace/tui/widgets/file_panel/_display.py`
- `src/sase/ace/tui/modals/notification_modal.py`
- shared graphics code in `src/sase/ace/tui/graphics/`

Existing tests only prove that image paths are routed to the preview layer and that the renderable emits control
segments. They do not prove that panel-specific sizing is based on the actual visible content region, that narrow panes
avoid wrapping Kitty placeholder rows, or that non-PNG image attachments get a useful inline preview path.

## Working Diagnosis

Image size can plausibly be the root of the panel failure, but the precise issue is not raw pixel dimensions. Kitty can
scale uploaded PNGs into a requested cell placement. The fragile part is the requested terminal-cell placement:

- The notification modal hardcodes `columns=40, rows=12`, regardless of the right pane's current width and height.
- The Agents tab file panel derives preview size from `self.size`, but the image is rendered inside a padded/bordered
  `VerticalScroll`; using the child size directly can overestimate the visible content region.
- If the placeholder row is wider than the actual viewport, Textual/Rich can crop or wrap the placeholder cells while
  the Kitty placement sequence still declares the larger geometry. That can make the terminal graphics placement appear
  blank, clipped, or visually disconnected from the panel.
- The preview layer currently treats `.jpg`, `.jpeg`, `.webp`, and `.gif` as supported image paths at the routing layer,
  but only PNG files render inline. Those formats intentionally fall back today, which can look like "Kitty images do
  not work" for common notification attachments.

The fix should therefore make cell placement fit the actual panel viewport, keep graceful fallbacks, and make
unsupported formats explicit rather than silently pretending they are fully supported.

## Plan

1. Add a shared image preview sizing helper for Textual widgets.
   - Compute available columns and rows from the live scroll/content region when possible.
   - Reserve rows for path headers and separators in the file panel.
   - Clamp to Kitty placeholder-safe bounds and to a conservative maximum.
   - Avoid a minimum size that can exceed the visible pane; if the pane is too small, return a fallback-sized preview or
     a clear text fallback rather than an overflowing placement.

2. Use the shared helper in both callers.
   - Replace the notification modal's fixed `40x12` preview with live sizing from `#notification-file-scroll` /
     `#notification-file-content`.
   - Update the Agents tab file panel to size against the scroll viewport, not only the `Static` child.
   - Keep scroll reset and cleanup-sequence behavior unchanged.

3. Tighten format semantics.
   - Keep broad attachment discovery for common raster files.
   - Make the renderable's inline Kitty path explicitly PNG-only until transcoding is implemented.
   - Improve fallback wording/tests so JPEG/WebP/GIF users see that the terminal path is working but inline rendering
     needs PNG bytes.

4. Add focused regression tests.
   - File panel sizing clamps to available panel geometry and does not request more cells than the viewport can show.
   - Notification modal sizing no longer hardcodes `40x12` and adapts to narrow/tall panes.
   - Tiny panes choose a bounded/fallback behavior instead of an impossible placement.
   - Existing PNG preview routing and cleanup behavior still work.
   - Non-PNG raster attachments produce the explicit fallback.

5. Verify.
   - Run the focused graphics and image panel tests.
   - Run `just check` after source changes, per repo instructions.

## Expected Outcome

Inline Kitty previews should render inside the visible file/notification panel instead of relying on a fixed or
overestimated cell placement. PNG attachments should display when terminal capability probing succeeds. Non-PNG raster
attachments should fail transparently with actionable fallback text rather than being confused with a Kitty/panel sizing
failure.
