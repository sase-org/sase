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

- `src/sase/ace/tui/graphics/capability.py:21` only models `GraphicsProtocol = Literal["kitty"]`.
- `src/sase/ace/tui/graphics/capability.py:162` runs an active TTY probe before Textual starts (the comment at
  `capability.py:1` notes the probe must run pre-`App.run()`, otherwise replies look like user input).
- `src/sase/ace/tui/graphics/renderable.py:67` uploads PNG bytes with Kitty control sequences, creates a Unicode-
  placeholder placement, and emits placeholder rows as Rich segments.
- `src/sase/ace/tui/graphics/images.py` recognizes `.png`, `.jpg`, `.jpeg`, `.webp`, and `.gif`, but
  `INLINE_IMAGE_EXTENSIONS` is restricted to `{".png"}` (everything else falls back to a text placeholder).
- `src/sase/ace/tui/graphics/sizing.py:14` derives placeholder dimensions from the visible scroll widget; this is the
  one place that already understands Textual layout state.
- The file panel and notification modal render images by placing this Rich renderable in a `Static` / scroll pane.

The only true inline path is: local PNG → successful pre-Textual Kitty probe → Kitty Unicode placeholders survive
Textual/Rich redraws and any tmux passthrough → placement dimensions match the visible panel.

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

### tmux Version Gates The Best Protocol Choice

The exact tmux capability matrix matters because the SASE deployment story almost always involves tmux:

- **tmux 3.3+** required for `allow-passthrough` (the option used by `tmux_passthrough_wrap` in
  `src/sase/ace/tui/graphics/kitty.py`). Below 3.3, no graphics protocol can reach the outer terminal at all.
- **Native Sixel** rendering is gated on a **build-time** `--enable-sixel` flag and is off in many distro packages. The
  `terminal-features` option must list `sixel` for tmux to accept the sequences. A tmux that wasn't built with Sixel
  cannot pass Sixel through either; it strips the DCS sequence.
- **Native Kitty Graphics Protocol** is **not supported by upstream tmux**. Upstream tracks this in tmux/tmux#4902;
  there is a proof-of-concept on the `ta/kitty-img` branch and the third-party `sixel-tmux` fork, but no released tmux
  version (through 3.5 at the time of writing) renders TGP itself. TGP only works inside tmux through APC passthrough
  to a TGP-aware outer terminal, with all the placement/layout fragility that implies.
- **iTerm2's inline image protocol** historically broke under tmux because of a 256-byte sequence limit. iTerm2 3.5+
  adds a `MultipartFile`/`FilePart`/`FileEnd` form that fits inside the 1 MiB-per-sequence ceiling and works under
  modern tmux/iTerm2 pairs.

The practical implication for SASE: every native graphics protocol has a non-trivial tmux story. Whichever is chosen
must be opt-in, and the default must not depend on it.

Sources:

- tmux manual, `terminal-features` and `sixel`: https://man7.org/linux/man-pages/man1/tmux.1.html
- tmux FAQ, passthrough escape sequence (`allow-passthrough` since tmux 3.3): https://github.com/tmux/tmux/wiki/FAQ
- tmux issue 4902 ("Support kitty image protocol"): https://github.com/tmux/tmux/issues/4902
- iTerm2 image protocol with tmux multipart form: https://iterm2.com/documentation-images.html

### iTerm2 / WezTerm Inline Image Protocol Is A Useful Second Native Backend

The iTerm2 inline image protocol uses an OSC `1337;File=…` sequence carrying base64-encoded raw image bytes (PNG, JPEG,
GIF, PDF, etc.) and accepts width/height in cells, pixels, or percent. WezTerm implements the same protocol and exposes
it via `wezterm imgcat`. This means a single iTerm2-protocol implementation can cover iTerm2, WezTerm, mintty, recent
Konsole, recent foot, and others.

Two reasons this matters for SASE:

1. The PNG-only restriction in SASE today is a Kitty implementation choice, not a fundamental terminal limit. iTerm2's
   protocol carries JPEG/GIF/WebP without re-encoding.
2. WezTerm is a major Textual user-base terminal and does not implement Kitty TGP; SASE's current path can never light
   up there.

WezTerm's own docs do warn that "the image protocol isn't fully handled by multiplexer sessions at this time," echoing
the tmux limitation noted above.

Sources:

- iTerm2 inline images protocol: https://iterm2.com/documentation-images.html
- WezTerm imgcat / iTerm2 protocol support: https://wezterm.org/imgcat.html

### `textual-image` Is Strong Prior Art, But A Risky Drop-In

The `textual-image` package is the most directly relevant Textual-specific project found. It provides both Rich
renderables (`textual_image.renderable.Image`) and Textual widgets (`textual_image.widget.Image`), with TGP, Sixel,
half-cell, and Unicode backends, and accepts Pillow images.

Important specifics from its own docs:

- Licensed **LGPL-3.0** (PyPI metadata sometimes shows the older "LGPLv3+" classifier). Linking from MIT-licensed SASE
  is workable, but vendoring or modifying the source is not.
- Terminal capability queries must happen before the Textual app starts, because Textual owns input/output after
  launch — the same constraint SASE already worked around in `capability.py`.
- TGP is explicitly considered unusable in tmux by this project.
- Sixel in Textual is "not particularly performant," with flicker during scrolling and style changes; high images break
  when the image height exceeds the terminal window.
- `textual-serve` is not supported.

For SASE, this is valuable prior art and a possible optional backend if LGPL-3.0 is acceptable, but it should not be
copied into the SASE codebase. It also should not be treated as a magic fix for Kitty-in-tmux.

Sources:

- textual-image PyPI metadata and README: https://pypi.org/pypi/textual-image/json
- textual-image project page: https://pypi.org/project/textual-image/
- textual-image repository: https://github.com/lnqs/textual-image

### `term-image` Is The MIT-Licensed Counterpart Worth Tracking

`term-image` is a Python image-rendering library that ships:

- Kitty graphics protocol backend.
- iTerm2 inline image protocol backend (covers WezTerm, mintty, etc.).
- Truecolor and 256-color Unicode block fallbacks.
- Animation support for GIF, WebP, and APNG with explicit frame iteration controls.
- Inputs from filesystem paths, URLs, or live `PIL.Image` instances.
- A `widget` module documented in the API reference, in addition to a CLI viewer.
- **MIT** license per its PyPI classifiers.

Compared to `textual-image`:

- License is permissive enough to vendor or fork if needed.
- It does not currently advertise a Sixel backend, which is fine for SASE because Sixel-in-Textual is the worst-rated
  path of the three regardless.
- Its Textual integration is less explicit than `textual-image`, but its widget module is the natural seam.

If SASE eventually adopts a third-party rendering library, `term-image` is the most license-compatible choice and
already covers the iTerm2 protocol that `textual-image` rates badly under tmux.

Sources:

- term-image PyPI metadata: https://pypi.org/pypi/term-image/json
- term-image documentation: https://term-image.readthedocs.io/

### Character-Cell Renderers Are The Reliable Baseline

`rich-pixels`, Chafa, `viu`, `timg`, and `term-image`'s block backends all demonstrate the same key idea: when native
terminal graphics are unavailable or unreliable, render an image as colored terminal cells. This loses fidelity but
works with normal terminal text rendering, which is exactly what Textual controls well.

Notable options:

- `rich-pixels` is a small MIT Rich renderable that works in Textual like any other Rich renderable.
- Chafa supports common image formats, animations, Sixel, Kitty, iTerm2, and Unicode mosaics, with a stable C API and
  Python bindings under active development. Its `--symbols` selector exposes half-block (`vhalf`), quadrant, sextant,
  and braille modes for varying density.
- `viu` is MIT and uses Kitty/iTerm when available, otherwise lower-half block output; its README explicitly notes that
  Kitty protocol and tmux do not get along.

#### Density Choices Inside The Cell Path

Half-block (`▀`/`▄`) gives a cell `cols × (rows × 2)` effective pixels. There are denser Unicode mosaic options:

- **Quadrant blocks** (U+2596–U+259F): `cols × 2 × rows × 2` — 4 pixels per cell at 8 distinct fill states.
- **Sextant blocks** (U+1FB00–U+1FB3B, Unicode 13.0, 2020): `cols × 2 × rows × 3` — 6 pixels per cell, ~3× the
  vertical density of half-blocks. Modern font support is broad on Linux/macOS terminals and good in WezTerm,
  Kitty, foot, Ghostty, iTerm2, and recent xterms; older terminals (and several monospace fonts) miss them.
- **Octant blocks** (U+1CD00–U+1CDE5, Unicode 16.0, 2024): `cols × 2 × rows × 4`. Font support is still spotty as of
  2026 and not safe to rely on by default.
- Braille (U+2800–U+28FF) gives 2×4 dots per cell but is monochrome; reasonable for line art only.

The default for SASE should stay at half-block because half-block colored output is universal in monospace fonts. A
sextant mode is a reasonable opt-in upgrade for users on terminals with confirmed font coverage.

Sources:

- Unicode "Symbols for Legacy Computing" block (sextants), U+1FB00 chart:
  https://www.unicode.org/charts/PDF/U1FB00.pdf
- Unicode block sextant character documentation: https://www.unicode.org/charts/nameslist/n_1FB00.html
- rich-pixels: https://github.com/darrenburns/rich-pixels
- Chafa: https://hpjansson.org/chafa/
- viu: https://github.com/atanunq/viu

### Backend / Terminal / Multiplexer Compatibility Matrix

| Backend                | Plain Kitty | Plain WezTerm | Plain iTerm2 | Plain xterm | tmux ≥ 3.3 + Kitty | tmux ≥ 3.5 + WezTerm | Generic SSH/VT |
| ---------------------- | ----------- | ------------- | ------------ | ----------- | ------------------ | -------------------- | -------------- |
| Kitty TGP placeholders | yes         | no            | no           | no          | fragile, APC       | no                   | no             |
| iTerm2 inline image    | no          | yes           | yes          | no          | no                 | partial (multipart)  | no             |
| Sixel (DCS)            | no¹         | partial       | partial      | depends     | requires           | requires             | no             |
|                        |             |               |              |             | `--enable-sixel`   | `--enable-sixel`     |                |
| Unicode half-block     | yes         | yes           | yes          | yes         | yes                | yes                  | yes²           |
| Unicode sextant        | yes         | yes           | yes          | yes³        | yes                | yes                  | yes³           |

¹ Kitty has historically rejected Sixel; recent builds added experimental Sixel acceptance, but TGP is the supported
path on Kitty itself.
² Requires truecolor or graceful 256-color downsampling for color fidelity.
³ Requires a font with `Symbols for Legacy Computing` glyphs.

## Recommendation

Make SASE's default inline preview a portable cell-rendered image, then layer native terminal graphics on top as an
optional high-fidelity renderer.

The most practical architecture is:

1. Add a small SASE-owned `ImagePreviewWidget` or renderable that uses Pillow to load any supported image type and
   render a bounded thumbnail as Rich segments using half-block cells.
2. Keep this portable renderer as the default for all terminals, including tmux, SSH, non-Kitty terminals, and failed
   graphics probes.
3. Add an iTerm2 inline-image backend alongside the existing Kitty backend so WezTerm and iTerm2 light up. Both native
   backends should be opt-in (or opt-out) and must fall back silently to the cell renderer.
4. Keep Kitty placeholder rendering only as an optional fast/high-fidelity path for known-good terminals. It should be
   allowed to fail without changing the user's ability to inspect the image.
5. Add a future Sixel backend only if there is a clear user need and only after validating flicker/performance in
   SASE's actual scroll panes; current evidence (textual-image's own warnings) is that Sixel-in-Textual is the worst of
   the three native options.
6. Treat `textual-image` as a benchmark/prototype target, not as code to vendor. If adopting it as a dependency, confirm
   LGPL-3.0 compatibility with SASE's licensing constraints. If a third-party rendering library is adopted instead,
   `term-image` (MIT) is the more permissively licensed pick.

## Why This Is Better Than Continuing Kitty-Only

The current implementation optimizes for the highest-fidelity case but has no good baseline. A cell-rendered preview
inverts that:

- It uses normal Textual/Rich rendering, so it is compatible with Textual's layout, scrolling, and testing model.
- It works for JPEG, WebP, GIF first frames, and PNG through one image-loading pipeline.
- It avoids pre-app terminal input probing for the baseline path.
- It behaves predictably inside tmux and over SSH.
- It gives SASE a real preview even when native terminal protocols fail.
- It still leaves room for Kitty/iTerm2/Sixel where they are actually reliable.

## Proposed Implementation Shape

### Phase 1: Portable Preview

- Add `pillow` as a dependency or optional extra used by ACE image previews.
- Implement a half-block renderable:
  - Open image with Pillow.
  - Convert to RGBA.
  - Fit to the visible panel cell dimensions while preserving aspect ratio.
  - Resize to `columns × rows*2` pixels.
  - Emit one terminal cell for each two vertical pixels using foreground/background truecolor.
  - When `has_truecolor()` is `False` (`capability.py:63`), fall back to a 256-color palette (e.g. xterm 6×6×6 cube)
    instead of failing.
  - Composite alpha against the panel background or a neutral dark background.
  - For GIF, render the first frame and state that animation is not shown in ACE; revisit animation only after the
    static path is solid.
- Cache by `(path, mtime_ns, file_size, columns, rows, background, palette_mode)` with a small LRU (e.g. 64 entries) to
  avoid recomputing on every redraw, scroll, or resize tick.
- Reuse `image_preview_size_for_viewport()` in `src/sase/ace/tui/graphics/sizing.py` for bounds; that helper already
  understands Textual scroll regions.
- Run Pillow decode + resize in `asyncio.to_thread` for files above a configurable byte threshold (e.g. 1 MiB) so the
  Textual event loop is not blocked while a multi-MB image is decoded. The cache lookup should stay synchronous.
- Add a max-pixel-count guardrail (decompression-bomb-style) before any decode; mirror Pillow's `MAX_IMAGE_PIXELS`
  limit but enforce it ourselves with a clear error string in the fallback renderable.
- Update the fallback copy so users see a preview first and can still open the real file in the editor/viewer.

### Phase 2: Renderer Selection

Generalize `GraphicsProtocol = Literal["kitty"]` in `src/sase/ace/tui/graphics/capability.py:21` to
`Literal["kitty", "iterm2"]` (and later `"sixel"`), keep the active-probe pattern from `_probe_kitty_graphics()`, and
add an analogous iTerm2 path that recognizes WezTerm/iTerm2 from `TERM_PROGRAM` plus a passive DA1 + XTGETTCAP probe.

Introduce a small renderer decision model:

```text
native_kitty_enabled && capability.protocol == "kitty"
  -> KittyImageRenderable (with format normalization to PNG via Pillow if needed)
elif native_iterm2_enabled && capability.protocol == "iterm2"
  -> Iterm2ImageRenderable
elif pillow_available
  -> CellImageRenderable
else
  -> ImageFallbackRenderable
```

The decision should be explicit in diagnostics so failures are explainable:

- `native=kitty skipped: tmux probe failed`
- `native=kitty skipped: non-PNG source normalized through cell renderer`
- `native=iterm2 selected: WezTerm detected, cells=64×18`
- `portable=cell rendered: 64×18 cells, palette=truecolor`
- `portable=cell unavailable: Pillow not installed`

### Phase 3: Optional Native Backends

Only after the portable path is solid:

- Add JPEG/WebP/GIF→PNG normalization for Kitty upload via Pillow (lifts the PNG-only restriction in
  `images.py` `INLINE_IMAGE_EXTENSIONS`).
- Add an iTerm2 inline-image renderable using OSC 1337. Use the new `MultipartFile` / `FilePart` / `FileEnd` form when
  inside tmux ≥ 3.5 to clear the legacy 256-byte cap; use the single-shot form otherwise.
- Consider Sixel for tmux users only after confirming the local tmux build advertises Sixel via
  `terminal-features` and that scrolling does not flicker in ACE's panes.
- Evaluate `textual-image` as an optional dependency or compare its behavior in a throwaway branch.
- Treat SVG and other vector formats as out-of-scope for the renderable; convert via CairoSVG / resvg / `rsvg-convert`
  in a one-shot helper that produces a cached PNG, then feed that into the same pipeline.

### Phase 4: Animation (Optional)

Animated GIF/WebP/APNG previews require a periodic `Static.update()` driven by a Textual `Timer`. Recommend deferring
this until phase 1–3 are stable: the cost is non-trivial (frame decoding + cache eviction + redraw scheduling) and the
value for agent-generated artifacts is unclear. If/when added, mirror `term-image`'s frame-iterator API rather than
reinventing it.

## Testing Plan

Automated tests should not require a real terminal graphics stack.

- Unit-test half-block rendering dimensions for wide, tall, tiny, transparent, and missing images.
- Unit-test renderer selection for Kitty success, Kitty failure, iTerm2 success, non-PNG input, missing Pillow, and
  256-color fallback.
- Unit-test the iTerm2 multipart form against a recorded fixture and confirm chunk size is below 1 MiB.
- Snapshot-test that the file panel and notification modal receive a Rich renderable with bounded dimensions.
- Keep current Kitty protocol tests as narrow protocol/unit tests.
- Add a manual smoke script that runs ACE in:
  - plain Kitty
  - Kitty + tmux ≥ 3.3
  - WezTerm (iTerm2 protocol)
  - WezTerm + tmux ≥ 3.5 (iTerm2 multipart)
  - a Sixel-capable terminal (e.g. xterm with `--enable-sixel`, foot, Konsole)
  - a generic terminal with no native image support (e.g. macOS Terminal.app)
  - an SSH-from-tmux session (tests the stripping/passthrough behavior end-to-end)

Manual success should be defined as "the user can identify the image inside the panel" for the portable path and
"native bitmap renders without corrupting the panel" for the optional path.

## Open Questions

- Is adding Pillow acceptable for core SASE, or should it be an ACE-only optional extra? Pillow is widely deployed but
  pulls C dependencies; the optional-extra route keeps the base install slim while still letting ACE light up by
  default in environments that need it.
- Should native terminal graphics default to off until explicitly enabled, given the history of failures? An
  environment-variable opt-out already exists (`SASE_TUI_GRAPHICS`, see `capability.py:102`); the inverse
  (default-off + opt-in) is feasible with the same control point.
- Does SASE need animated GIF preview, or is first-frame preview enough for generated-agent artifacts?
- Does SASE want a sextant-density opt-in, given that font coverage is now broad? Recommend gating on a
  `SASE_TUI_IMAGE_DENSITY=sextant` env var rather than auto-detecting font support, which is unreliable.
- Should image preview rendering eventually move into the Rust core if other frontends need identical thumbnail logic?
  Per `memory/short/rust_core_backend_boundary.md`, the litmus test is "would another frontend (web, CLI, editor)
  need the same behavior to match the TUI?" Thumbnail dimensions and pixel-to-cell mapping arguably yes; raw terminal
  protocol emission is presentation-only and stays in Python.
- License decision: if a third-party rendering library is eventually adopted, is LGPL-3.0 (`textual-image`) acceptable
  in addition to MIT (`term-image`)? Resolve this before any vendoring or hard dependency.

## Bottom Line

Stop treating Kitty as the primary inline image renderer. Use a Textual-native, Rich/cell-based preview as the default
inside SASE, generalize `GraphicsProtocol` so iTerm2 can ride alongside Kitty for WezTerm/iTerm2 users, and keep
Kitty/Sixel as opportunistic upgrades. This matches Textual's strengths, works in tmux ≥ 3.3, supports all collected
image formats, and still leaves a path to high-fidelity terminal graphics where the user's terminal stack actually
supports it.
