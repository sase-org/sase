---
create_time: 2026-05-07
status: research
---

# Rendering Images Inside SASE Textual Panels

## Question

SASE currently attempts inline image rendering through a Kitty-only graphics path, but it has not worked reliably in the
ACE/Textual UI. What is a better way to render images inside the Textual framework?

## Current SASE State

The current implementation is a bespoke Kitty Graphics Protocol integration:

- `src/sase/ace/tui/graphics/capability.py` only models `GraphicsProtocol = Literal["kitty"]`.
- `src/sase/ace/tui/graphics/renderable.py` uploads PNG bytes with Kitty control sequences, creates a Unicode-placeholder
  placement, and emits placeholder rows as Rich segments.
- `src/sase/ace/tui/graphics/images.py` recognizes `.png`, `.jpg`, `.jpeg`, `.webp`, and `.gif`, but
  `INLINE_IMAGE_EXTENSIONS` is only `{".png"}`.
- The file panel and notification modal render images by placing this Rich renderable in a `Static` / scroll pane.

This means the only true inline path is: local PNG -> successful pre-Textual Kitty probe -> Kitty Unicode placeholders
survive Textual/Rich redraws and any tmux passthrough -> placement dimensions match the visible panel.

That path is inherently narrow. Even if it works in a plain Kitty shell, it is fragile in SASE's real environment:
Textual redraws widgets, tmux often hides or mediates terminal capabilities, the code only handles PNG, and a mismatch
between the printed placeholder grid and the actual visible cell region can clip or blank the image.

## External Findings

### Textual Does Not Have Native Image Support Yet

Textual's FAQ says it does not have built-in image support yet and points users toward third-party Rich renderables such
as `rich-pixels`. Textual does support Rich renderables in widgets like `Static`, and `Static.update()` accepts Rich
renderables, so image rendering needs to arrive as a renderable or custom widget rather than a first-party Textual
feature.

Sources:

- Textual FAQ: https://textual.textualize.io/FAQ/#does-textual-support-images
- Textual Static widget docs: https://textual.textualize.io/widgets/static/
- Textual widget guide, Rich renderables and line API: https://textual.textualize.io/guide/widgets/

### Kitty Placeholders Are The Right Shape For TUIs, But Not Sufficient

Kitty's Unicode placeholder mode was designed for host applications such as tmux, vim, and other Unicode-aware apps:
the app prints placeholder cells, and the terminal maps them to an uploaded image. The protocol also explicitly notes
that images can be fitted to a rectangle of terminal columns and rows, and that if printed placeholders do not match the
placement rectangle, only part of the image may be displayed.

This validates SASE's current architectural idea, but it also explains the fragility: the host application's text layout
must preserve the placeholder grid exactly, and the terminal side must support the protocol all the way through.

Source:

- Kitty graphics protocol, Unicode placeholders: https://sw.kovidgoyal.net/kitty/graphics-protocol/#unicode-placeholders

### tmux Changes The Best Protocol Choice

tmux's own documentation exposes `terminal-features`, including `sixel`, and describes `client_termfeatures` /
`client_termname` as client properties. Its FAQ says passthrough sequences require `allow-passthrough` in recent tmux
versions and warns that tmux is not aware of state changes caused by passthrough escapes.

The practical implication for SASE: Kitty passthrough can work for some setups, but tmux is not a transparent Kitty
terminal. A robust SASE preview should not require Kitty TGP to be the only successful path inside tmux.

Sources:

- tmux manual, `terminal-features` and `sixel`: https://man7.org/linux/man-pages/man1/tmux.1.html
- tmux FAQ, passthrough escape sequence: https://github.com/tmux/tmux/wiki/FAQ

### `textual-image` Is Strong Prior Art, But A Risky Drop-In

The `textual-image` package is the most directly relevant Textual-specific project found. It provides both Rich
renderables and Textual widgets, supports Terminal Graphics Protocol, Sixel, half-cell, and Unicode fallbacks, and
supports image inputs through Pillow. Its current PyPI metadata lists LGPLv3+ classifiers.

Important limitations from its own docs:

- Terminal capability queries must happen before the Textual app starts, because Textual owns input/output after launch.
- TGP is not considered usable in tmux by that project; tmux works through Sixel when the outer stack supports it.
- Sixel in Textual is described as not particularly performant, with possible flicker during scrolling/style changes.
- `textual-serve` is not supported.

For SASE, this is valuable prior art and maybe an optional backend if LGPLv3+ is acceptable, but it should not be copied
into the MIT codebase. It also should not be treated as a magic fix for Kitty-in-tmux.

Sources:

- textual-image PyPI metadata and README: https://pypi.org/pypi/textual-image/json
- textual-image project page: https://pypi.org/project/textual-image/
- textual-image repository: https://github.com/lnqs/textual-image

### Character-Cell Renderers Are The Reliable Baseline

`rich-pixels`, Chafa, and `viu` all demonstrate the same key idea: when native terminal graphics are unavailable or
unreliable, render an image as colored terminal cells. This loses fidelity but works with normal terminal text rendering,
which is exactly what Textual controls well.

Notable options:

- `rich-pixels` is a small MIT Rich renderable that works in Textual like any other Rich renderable.
- Chafa supports common image formats, animations, Sixel, Kitty, iTerm2, and Unicode mosaics, with a stable C API and
  Python bindings in development.
- `viu` is MIT and uses Kitty/iTerm when available, otherwise lower-half block output; its README explicitly notes that
  Kitty protocol and tmux do not get along.

Sources:

- rich-pixels: https://github.com/darrenburns/rich-pixels
- Chafa: https://hpjansson.org/chafa/
- viu: https://github.com/atanunq/viu

## Recommendation

Make SASE's default inline preview a portable cell-rendered image, then layer native terminal graphics on top as an
optional high-fidelity renderer.

The most practical architecture is:

1. Add a small SASE-owned `ImagePreviewWidget` or renderable that uses Pillow to load any supported image type and render
   a bounded thumbnail as Rich segments using half-block cells.
2. Keep this portable renderer as the default for all terminals, including tmux, SSH, non-Kitty terminals, and failed
   graphics probes.
3. Keep Kitty placeholder rendering only as an optional fast/high-fidelity path for known-good terminals. It should be
   allowed to fail without changing the user's ability to inspect the image.
4. Add a future Sixel backend only if there is a clear user need and only after validating flicker/performance in SASE's
   actual scroll panes.
5. Treat `textual-image` as a benchmark/prototype target, not as code to vendor. If adopting it as a dependency, do a
   deliberate license and behavior review first.

## Why This Is Better Than Continuing Kitty-Only

The current implementation optimizes for the highest-fidelity case but has no good baseline. A cell-rendered preview
inverts that:

- It uses normal Textual/Rich rendering, so it is compatible with Textual's layout, scrolling, and testing model.
- It works for JPEG, WebP, GIF first frames, and PNG through one image-loading pipeline.
- It avoids pre-app terminal input probing for the baseline path.
- It behaves predictably inside tmux and over SSH.
- It gives SASE a real preview even when native terminal protocols fail.
- It still leaves room for Kitty/Sixel where they are actually reliable.

## Proposed Implementation Shape

### Phase 1: Portable Preview

- Add `pillow` as a dependency or optional extra used by ACE image previews.
- Implement a half-block renderable:
  - Open image with Pillow.
  - Convert to RGBA.
  - Fit to the visible panel cell dimensions while preserving aspect ratio.
  - Resize to `columns x rows*2` pixels.
  - Emit one terminal cell for each two vertical pixels using foreground/background truecolor.
  - Composite alpha against the panel background or a neutral dark background.
  - For GIF, render the first frame and state that animation is not shown in ACE.
- Cache by `(path, mtime_ns, size, columns, rows, background)` to avoid recomputing on every redraw.
- Use the existing `image_preview_size_for_viewport()` helper for bounds.
- Update the fallback copy so users see a preview first and can still open the real file in the editor/viewer.

### Phase 2: Renderer Selection

Introduce a small renderer decision model:

```text
native_kitty_enabled && path_can_be_uploaded && capability_supported
  -> KittyImageRenderable
else pillow_available
  -> CellImageRenderable
else
  -> ImageFallbackRenderable
```

The decision should be explicit in diagnostics so failures are explainable:

- `native=kitty skipped: tmux probe failed`
- `native=kitty skipped: non-PNG source normalized through cell renderer`
- `portable=cell rendered: 64x18 cells`
- `portable=cell unavailable: Pillow not installed`

### Phase 3: Optional Native Backends

Only after the portable path is solid:

- Add JPEG/WebP/GIF-to-PNG normalization for Kitty upload if native rendering remains useful.
- Consider Sixel for tmux users if local testing shows it renders acceptably in ACE's scroll panes.
- Evaluate `textual-image` as an optional dependency or compare its behavior in a throwaway branch.

## Testing Plan

Automated tests should not require a real terminal graphics stack.

- Unit-test half-block rendering dimensions for wide, tall, tiny, transparent, and missing images.
- Unit-test renderer selection for Kitty success, Kitty failure, non-PNG input, and missing Pillow.
- Snapshot-test that the file panel and notification modal receive a Rich renderable with bounded dimensions.
- Keep current Kitty protocol tests as narrow protocol/unit tests.
- Add a manual smoke script that runs ACE in:
  - plain Kitty
  - Kitty + tmux
  - WezTerm or another Sixel-capable terminal
  - a generic terminal with no native image support

Manual success should be defined as "the user can identify the image inside the panel" for the portable path and "native
bitmap renders without corrupting the panel" for the optional path.

## Open Questions

- Is adding Pillow acceptable for core SASE, or should it be an ACE-only optional extra?
- Should native terminal graphics default to off until explicitly enabled, given the history of failures?
- Does SASE need animated GIF preview, or is first-frame preview enough for generated-agent artifacts?
- Should image preview rendering eventually move into the Rust core if other frontends need identical thumbnail logic?
  For now, this is presentation behavior and can stay in Python/Textual.

## Bottom Line

Stop treating Kitty as the primary inline image renderer. Use a Textual-native, Rich/cell-based preview as the default
inside SASE, and keep Kitty/Sixel as opportunistic upgrades. This matches Textual's strengths, works in tmux, supports
all collected image formats, and still leaves a path to high-fidelity terminal graphics where the user's terminal stack
actually supports it.
