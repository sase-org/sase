# TUI image and PDF support — research

Goal: let the sase TUI (Textual app under `src/sase/ace/tui/`) render images
and PDFs inline when the user is on a graphics-capable terminal — primary
target **Kitty** — and degrade cleanly otherwise. **Must work over SSH.**

This doc is a scoping reference, not an implementation plan. It is opinionated
where the trade-offs are clear and flags open questions where they aren't.

Second-pass update: April 30, 2026.

---

## TL;DR

1. **Bet on the Kitty graphics protocol (TGP) with Unicode placeholders.** It
   is the only mode that survives a Textual app's frequent redraws cleanly,
   and it is the only mode that survives tmux passthrough. Kitty originated
   it; Ghostty documents support; WezTerm should be treated as probe-only for
   TGP placeholders and covered through Sixel when needed.
2. **For SSH, force `t=d` (direct/stream) and PNG (`f=100`).** File and
   shared-memory transmission modes don't work remotely; PNG is already
   compressed so it is by far the cheapest to ship. Upload **once** by image
   ID, then issue many cheap placements.
3. **Use `pypdfium2` for PDF rasterization.** Apache/BSD-licensed, no system
   deps, fast enough for interactive page-at-a-time use. PyMuPDF is faster
   but AGPL-3.0, which would force sase to AGPL or buy a commercial license.
4. **Do not add a graphics library dependency until the license decision is
   explicit.** The earlier version of this doc called `textual-image` MIT;
   current PyPI metadata says **LGPLv3+**, and `textual-kitty` is **GPLv3+**.
   They are good references/prototype dependencies, but an MIT project like
   sase should probably ship a small internal TGP/placeholder encoder unless
   we are comfortable carrying LGPL obligations.
5. **Probe protocol support exactly once, before `App.run()` starts.** The
   Textual input loop will eat the response to a `\e_Gi=...,a=q;...\e\\`
   query if you probe after startup.
6. **First integration target should be existing file-preview surfaces.**
   `AgentFilePanel.display_static_file()` and `NotificationModal._display_file()`
   already route attached files through narrow rendering paths; adding
   image/PDF handling there exercises the feature without redesigning the TUI.

---

## 1. Why this is non-trivial in a TUI

Inline images in a *one-shot* tool like `kitten icat` are easy: emit escape
sequences at the cursor and exit. In a Textual app the screen redraws
constantly, the alt-screen is in use, widgets move on resize, the user
scrolls long lists, and the app multiplexes via tmux/SSH. Three problems
that don't exist in icat dominate the design:

- **Redraw stability.** A naive "print escape sequence per render frame"
  approach either flickers or leaves stale images. Need a way to anchor
  pixels to *cells* the framework already manages.
- **Hole-punching through Textual's renderer.** Textual composes the screen
  out of `Strip`s of `Segment`s. Raw control bytes are second-class — you
  emit them via `Segment(text, control=True)` so the diff renderer leaves
  them alone.
- **Capability detection without breaking input.** The standard probe
  (`\e_Gi=N,a=q;<payload>\e\\` → reply on stdin) collides with Textual's
  input thread once the app is running. Probe at startup, cache the result.

---

## 2. Kitty graphics protocol primer

Spec: <https://sw.kovidgoyal.net/kitty/graphics-protocol/>.

**Wire format** — APC sequence:

```
ESC _ G <comma-separated key=value control data> ; <base64 payload> ESC \
```

Key control fields you'll actually use:

| Key | Purpose |
| --- | --- |
| `a=` | action: `t` transmit, `T` transmit+display, `p` place existing, `d` delete, `q` query support |
| `f=` | format: `100` PNG (recommended), `32` RGBA, `24` RGB |
| `t=` | transport: `d` direct/inline (only choice over SSH), `f` file, `t` temp file, `s` shared mem |
| `o=z` | zlib-compress payload (no-op for PNG; useful for RGBA) |
| `i=` | 32-bit image ID (host-assigned) |
| `I=` | image number; terminal returns the allocated image ID |
| `p=` | placement ID (multiple placements of one image) |
| `m=1` / `m=0` | chunked transmission — required when payload >4096 B (almost always) |
| `c=`, `r=` | display columns/rows |
| `C=1` | do not move the cursor after direct placement; mostly irrelevant to placeholders |
| `q=2` | suppress OK responses |
| `U=1` | virtual placement, used with Unicode-placeholder mode |

**Two display modes — pick the right one:**

- **Direct placement** (`a=T` at cursor): terminal anchors the image at the
  cursor's cell coordinates at the time of the escape. Image stays put even
  when underlying text scrolls; the host has to manually delete or
  re-anchor. Bad for Textual.
- **Unicode placeholders** (`a=p, U=1, i=<id>` virtual placement, then print
  cells of `U+10EEEE` styled with the image-ID encoded in the foreground
  color and row/col encoded in combining diacritics from Unicode class 230,
  e.g. `U+0305`, `U+030D`, …): the image is *just text* from the
  application's point of view. When Textual moves the placeholder cells,
  the terminal repositions the bitmap automatically. Survives tmux
  passthrough. **This is the right primitive for a Textual host.** See the
  [Unicode placeholders section](https://sw.kovidgoyal.net/kitty/graphics-protocol/#unicode-placeholders)
  and [PoC discussion #4021](https://github.com/kovidgoyal/kitty/discussions/4021).

Placeholder details that matter for implementation:

- The image ID is encoded in foreground color. In 256-color mode that gives
  only 8 bits; in truecolor it gives 24 bits. Kitty also allows a third
  diacritic to carry the most-significant image-ID byte, but the simplest
  sane sase policy is "require truecolor for TGP placeholders" and keep image
  IDs within 24 bits.
- The placement ID is encoded in underline color. Use it if multiple
  placements of the same image can coexist; otherwise the terminal may choose
  any matching virtual placement.
- Diacritics can be compressed by inheritance from the previous placeholder
  cell, but don't do that in v1. Emit explicit row/column diacritics for
  easier debugging.

**Persistence.** Uploaded images live in the terminal independently of
placements; the alt-screen toggle does not delete them. Re-emitting the
same `i=`/`p=` is a no-op for the bytes — the terminal keys uploads by ID.
Pattern: **upload once, place many.**

**Cleanup.** `a=d, d=I, i=<id>` (capital `I` frees the bitmap; lowercase `i`
only frees placements). Long-lived sessions that don't free will leak.

---

## 3. SSH considerations

The protocol itself is in-band (escape sequences on the TTY), so it crosses
SSH transparently. The friction is elsewhere:

- **Local-only transports break.** `t=f` (path), `t=t` (temp file with
  `tty-graphics-protocol` in the name), `t=s` (POSIX shm) all assume a
  shared filesystem/kernel with the terminal emulator. Over SSH you must
  use `t=d`. `kitten icat`'s `--transfer-mode stream` is the safe knob.
- **Chunking is not optional over SSH.** Kitty's spec says remote clients
  must base64-encode and split direct payloads into chunks no larger than
  4096 bytes, with `m=1` for continuing chunks and `m=0` for the last chunk.
  Only the first chunk carries full metadata.
- **Terminfo.** `TERM=xterm-kitty` doesn't ship with most distros' ncurses,
  so curses-based tools on the remote misbehave (graphics still work).
  [`kitten ssh`](https://sw.kovidgoyal.net/kitty/kittens/ssh/) auto-installs
  the terminfo entry on the remote and is the user-friendly path. Manual
  fallback:

  ```bash
  infocmp -a xterm-kitty | ssh remote tic -x -o ~/.terminfo /dev/stdin
  ```

- **tmux is a separate hop.** tmux does not understand TGP as a native image
  protocol; it must be configured to pass the underlying terminal escape
  sequences through. Modern tmux exposes the pane option
  `allow-passthrough [on|off|all]`; `on` only permits passthrough for visible
  panes. Escape bodies must be wrapped as DCS passthrough
  `ESC Ptmux; ... ESC \`, with each embedded `ESC` doubled.
- **Bandwidth.** Worst case base64 is ~1.33× the raw bytes, plus chunk
  overhead. Mitigations, in priority order:
  1. **Send PNG (`f=100`)** instead of raw RGBA. PNG is already DEFLATE-
     compressed; this is the single biggest win for photos and PDF pages.
  2. **Downscale to display size before sending.** Query `CSI 16 t` for
     cell pixel dims and `CSI 14 t` for text-area pixel dims, scale the
     image so it fits the widget rect, *then* encode. Sending pixels much
     bigger than the rendered cells is pure waste.
  3. **Cache by image ID on the *remote* side.** Upload each logical image
     exactly once per session; every redraw is just a placement. Critical
     for SSH UX.
  4. `o=z` zlib for RGBA; no-op for PNG.

---

## 4. Protocol landscape and detection (April 2026)

Coverage from <https://www.arewesixelyet.com/> and terminal release notes:

| Terminal | Kitty TGP | Sixel | iTerm2 OSC 1337 |
| --- | --- | --- | --- |
| Kitty | ✅ origin | ❌ by design | ❌ |
| Ghostty | ✅ documented support | ❌ | ❌ |
| WezTerm | optional/partial; probe | ✅ | ✅ |
| iTerm2 3.3+ | partial | ✅ | ✅ origin |
| Konsole 22.04+ | partial | ✅ | ❌ |
| foot 1.2+ | ❌ | ✅ | ❌ |
| xterm (vt340) | ❌ | ✅ | ❌ |
| Windows Terminal 1.22+ | ❌ | ✅ | ❌ |
| Alacritty | ❌ | ❌ | ❌ |
| Warp | false-positive risk | ❌ | ❌ |

A Kitty-first strategy with TGP covers Kitty and Ghostty cleanly. WezTerm has
an `enable_kitty_graphics=true` knob, but `textual-image`'s current support
matrix treats TGP there as not usable for its placeholder-based renderer and
falls back to Sixel. Do not hard-code terminal names into a capability table;
probe the actual features.

Adding Sixel covers WezTerm + iTerm2 + foot + Konsole + xterm + Windows
Terminal + mlterm. iTerm2 OSC 1337 is largely redundant once you have TGP and
Sixel. For everything else, fall back to Unicode half-blocks (`▀` U+2580 with
foreground=top pixel, background=bottom pixel — doubles vertical resolution).

**Detection — there is no terminfo cap for graphics.** The reliable methods:

- **TGP probe**: send `\e_Gi=31337,a=q,t=d,f=24,s=1,v=1;AAAA\e\\`
  followed by primary device attributes (`\e[c`). If the device attributes
  response arrives but the graphics response does not, the terminal does not
  support TGP. This mirrors Kitty's spec and distinguishes "unsupported APC"
  from "terminal did not answer at all."
- **Placeholder probe**: plain TGP support is not enough for Textual. Warp and
  some partial implementations can answer graphics probes but fail Unicode
  placeholders. For v1, only enable the TGP backend after both a graphics
  query succeeds and the terminal family is known to support placeholders
  (Kitty/Ghostty), or after a future active placeholder smoke test.
- **Sixel probe**: primary device attributes (`CSI c`); presence of `4` in
  the response means Sixel.
- **iTerm2**: `TERM_PROGRAM=iTerm.app` env var.
- **Env hints (fast path before probing):** `KITTY_WINDOW_ID` (Kitty only —
  Ghostty/WezTerm don't set it), `TERM_PROGRAM`, `KONSOLE_VERSION`,
  `WEZTERM_EXECUTABLE`, `GHOSTTY_RESOURCES_DIR`.

Probe inside tmux is famously flaky — replies sometimes leak into pane
title parsing ([opentui#334](https://github.com/anomalyco/opentui/issues/334)).
Keep a short timeout and accept "no graphics" gracefully.

---

## 5. Python library options

| Library | Protocols | Textual? | License | Notes |
| --- | --- | --- | --- | --- |
| [`textual-image`](https://github.com/lnqs/textual-image) | TGP + Sixel + halfblock + unicode | first-class widget | **LGPLv3+** | Closest technical match. Current PyPI: 0.12.0, Apr 12 2026. Open issues: tmux passthrough wrapping (#104), Sixel scroll bleed (#69, #77), maintainer availability (#103, Apr 2026). |
| [`textual-kitty`](https://pypi.org/project/textual-kitty/) | TGP only + halfblock fallback | first-class widget | **GPLv3+** | Avoid as a dependency for MIT sase unless the project accepts GPL obligations; useful as a reference only. |
| [`term-image`](https://pypi.org/project/term-image/) | TGP + iTerm2 + blocks | adapter, not Textual-native | MIT | Mature but not Textual-native; pre-1.0 with explicit minor-version-breakage warning. No Sixel backend in current PyPI description. |
| [`textual-imageview`](https://github.com/adamviola/textual-imageview) | block-only | first-class widget | MIT | Block fallback only, but the cleanest pan/zoom UX in Textual — copy its keymap. |
| [`chafa.py`](https://github.com/GuardKenzie/chafa.py) | all (via chafa C lib) | no | LGPLv3 | Fastest halfblock/Sixel encoder; produces an ANSI string you can drop into a `Static`. Useful as a prototype/fallback reference, but has LGPL obligations. |

**Recommendation.** Use `textual-image` as a spike/reference, not as the
default production dependency yet. For production, the lowest-risk path is:

1. Add optional `pillow` + `pypdfium2` dependencies for rasterization.
2. Implement a small internal Kitty TGP backend: direct transport, PNG,
   chunking, virtual placement, placeholder cells, deletion, tmux wrapping.
3. Add a simple pure-Python halfblock fallback.
4. Defer Sixel until the first TGP/halfblock version is useful, or use
   `textual-image`/`chafa.py` behind an optional extra if license review says
   that is acceptable.

`kitten icat`'s [transmission logic](https://github.com/kovidgoyal/kitty/blob/master/kittens/icat/main.py)
is the canonical reference if we end up vendoring our own.

---

## 6. Textual integration pattern

The Strip-based architecture for an image widget:

1. **Before `AceApp.run()`:** probe TGP + Sixel, cache results in a
   module-level `Capabilities` dataclass. The right hook is in
   `src/sase/main/ace_handler.py` before the call to `app.run()`, not in
   `AceApp.on_mount()`, because Textual has already started its input
   machinery by mount time.
2. **On `Widget.on_mount`:** load image to PIL, downscale to widget pixel
   rect (cols × cell_w_px, rows × cell_h_px), encode to PNG, base64,
   chunk-emit `a=t, i=<id>, U=1, f=100` with `m=1`/`m=0`. Keep the ID on
   the widget. Then register a virtual placement: `a=p, U=1, i=<id>,
   c=<cols>, r=<rows>`.
3. **In `render_line(y)`:** build a `Strip` whose visible cells are
   `U+10EEEE` characters. Foreground color encodes the image ID (24-bit
   truecolor → 24-bit ID; require `COLORTERM=truecolor`, else 8-bit).
   Underline color encodes the placement ID. Combining diacritics from
   Unicode class 230 (`U+0305` row/col 0, `U+030D` row/col 1, `U+030E`
   row/col 2, …) encode the (row, col) within the image. Use
   `Segment(text, control=False)` — these are *real text cells*, not
   control sequences.
4. **On widget resize:** re-render the PIL image at the new pixel rect,
   re-upload with a new image ID, free the old one.
5. **On `Widget.on_unmount`:** `a=d, d=I, i=<id>`.

For inline images inside `RichLog` / `Markdown` / `Static`: build a Rich
renderable whose `__rich_console__` yields `Segment` lines of
placeholder cells. `textual_image.renderable.Image` does exactly this and
can be appended to a `RichLog` or returned from `Static.render()`.

For sase specifically, favor a `Static`-compatible renderable first. Both
`AgentFilePanel` and `NotificationModal` already call `Static.update()` with
`Syntax`, `Text`, or `Group` renderables. A renderable image/PDF preview can
slot into those surfaces before we build a dedicated pan/zoom widget.

**Avoid direct placement inside Textual.** The cursor coordinate moves
between frames, which means re-emitting placements either flickers or
strands stale images. Reserve direct placement for full-screen splash
screens where the alt-screen contents are stable.

Reference: [Rich images discussion #384](https://github.com/Textualize/rich/discussions/384),
[Textual Strip API](https://textual.textualize.io/api/strip/).

---

## 7. PDF rendering

Three real choices for "PDF page → PIL Image":

| Library | License | Engine | Trade-off |
| --- | --- | --- | --- |
| **`pypdfium2`** | Apache-2.0 / BSD-3 | Google PDFium | Permissive, no system deps (PDFium ships in the wheel), fast enough. **Default choice.** |
| `pymupdf` / `fitz` | **AGPL-3.0** or commercial | MuPDF | Fastest, richest API. AGPL forces sase to AGPL unless we buy a license. ([discussion](https://github.com/pymupdf/PyMuPDF/discussions/971)) |
| `pdf2image` | MIT wrapper, GPL-2 poppler | shell-out to `pdftoppm` | Requires system `poppler-utils`; ~10× slower. |

Sample API:

```python
import pypdfium2 as pdfium
pdf = pdfium.PdfDocument(path)
page = pdf[index]
w_pts, h_pts = page.get_size()           # PDF user units (1/72")
scale = target_px_w / w_pts              # pick scale to fit widget rect
pil_image = page.render(scale=scale).to_pil()
```

For better PIL interop, pypdfium2's docs call out pixel-format knobs such as
`force_bitmap_format=pdfium_c.FPDFBitmap_BGRA` plus `rev_byteorder=True`.
Benchmark that before assuming the default render path is cheapest.

**Resolution targeting.** Compute `target_px = (cols * cell_w_px,
rows * cell_h_px)` from `CSI 14t` / `CSI 16t`, fall back to 8×16 if the
queries time out. Pick `scale` to fit within `target_px` preserving aspect.

**Page navigation UX.** Lazy: render page on demand, LRU-cache N pages
(8 is plenty), prefetch N±2 on a background asyncio task. Re-render on
widget resize. For a 1000-page PDF this is the only viable approach.

**Text-extraction overlay (also serves as accessibility/no-graphics
fallback).** `pypdfium2`'s `page.get_textpage().get_text_range()` gives
raw text and `.get_rect()` gives bounding boxes — enough for a
search-and-highlight feature later.

**Security posture.** PDF parsing is a larger attack surface than displaying
PNG/JPEG files. Render PDFs only from explicit user-selected local files or
agent artifacts, cap page pixel dimensions before rasterization, impose a
reasonable file-size/page-count guard, and make failures degrade to "open in
editor/pager" rather than crashing the TUI.

---

## 8. Sharp edges

- **Cells aren't square** (typically 2:1 height:width). Scale by both axes
  separately, never just by columns. Prefer `TIOCGWINSZ` when it returns
  pixel dimensions, because it avoids another terminal query; use `CSI 14 t`
  / `CSI 16 t` as fallbacks. If everything times out, fall back to 8×16.
  ([CSI 14t reference](https://terminalguide.namepad.de/seq/csi_st-14/))
- **Direct-placed images don't clip to widget bounds.** Unicode
  placeholders sidestep this — clipping is automatic because cells outside
  the widget rect simply aren't printed.
- **tmux passthrough** requires `set -g allow-passthrough on` and
  per-escape wrapping (`\ePtmux;<body with each ESC doubled>\e\\`).
  Naive emission is silently dropped. Unicode placeholders inside
  passthrough is the only path that works in production. `textual-image`
  issue [#104](https://github.com/lnqs/textual-image/issues/104) is open
  on this as of April 2026 — be prepared to patch or vendor.
- **Probe must run pre-`App.run()`** — Textual's input thread eats
  responses otherwise. Cache the result for the session.
- **`COLORTERM=truecolor`** is required for 24-bit image-ID encoding.
  Otherwise cap at 256 simultaneous images.
- **Free images aggressively** with `a=d, d=I, i=<id>`. Long sessions
  otherwise accumulate uploads in the terminal's image store.
- **`textual-serve` (web-served Textual)** isn't supported by
  `textual-image` and won't work with TGP at all (the wire isn't a real
  TTY). If sase ever ships a web TUI, plan for the halfblock fallback
  there.
- **Don't auto-render huge media.** For images, cap decoded pixels before
  scaling to avoid decompression bombs. For PDFs, cap file size, page count,
  and target raster size. This is especially important for notification
  attachments produced by agents.

---

## 9. Reference projects worth reading

1. **[`textual-image`](https://github.com/lnqs/textual-image)** —
   `src/textual_image/renderable/tgp.py` and `widget.py`. Closest match to
   our architecture: chunked upload, virtual placement, placeholder Strip
   generation, capability detection ordering.
2. **[`textual-kitty`](https://pypi.org/project/textual-kitty/)** — smaller
   surface area, easier to lift patterns from.
3. **[`kitten icat`](https://github.com/kovidgoyal/kitty/blob/master/kittens/icat/main.py)** —
   `transmit_image()` for chunked encoding, `place_image()` for placement
   parameters, `--unicode-placeholder` branch for placeholder generation,
   `--detect-support` for the canonical query.
4. **[`viuer`](https://docs.rs/viuer)** (Rust) — clean separation between
   protocol detection and per-protocol encoders; structural reference even
   though we're staying in Python.
5. **[`timg`](https://github.com/hzeller/timg)** — graceful degradation
   across all three protocols + quarter-block fallback (C++).

---

## 10. Risks and open questions

- **License drift changed the recommendation.** `textual-image` is currently
  LGPLv3+ and `textual-kitty` is GPLv3+ on PyPI. The previous version of this
  research incorrectly listed both as MIT. Decide whether LGPLv3+ is acceptable
  for an optional runtime dependency; do not vendor LGPL/GPL code into the MIT
  tree without an explicit decision.
- **`textual-image` maintainer availability.** Issue
  [#103 (Apr 2026)](https://github.com/lnqs/textual-image/issues/103) raises
  the question. Decide whether to depend, vendor, or fork. A vendored copy
  of just the TGP encoder would need to be written from spec or copied only
  from license-compatible code.
- **tmux passthrough correctness in `textual-image` (#104).** Open as of
  April 2026. If sase users routinely run inside tmux on the remote side
  (likely — it's the standard SSH workflow), this will be the single most
  visible bug. Plan to either land a PR upstream or vendor with the fix.
- **Detection inside tmux** is unreliable. Decide policy: trust env
  hints + a hard `TMUX` opt-out, or probe with a tight timeout and accept
  the occasional false negative.
- **Use cases inside sase.** The smallest-blast-radius use cases are:
  - Notification attachments: `src/sase/ace/tui/modals/notification_modal.py`
    already displays attached files in `_display_file()`.
  - Agent file panel: `src/sase/ace/tui/widgets/file_panel/_display.py`
    already centralizes static file rendering in `display_static_file()`.
  - The `sase xprompt` PDF catalog already produced at
    `src/sase/main/xprompt_handler.py:187`.
  - Plan files / agent run artifacts that include images.
  - ChangeSpec inline content / agent screenshots, once the lower-level file
    preview path is stable.
- **AGPL boundary.** If anyone proposes PyMuPDF for "just a bit faster
  rendering," this needs to be a `just lint`-equivalent gate. Default to
  `pypdfium2`.
- **Rust backend.** sase has a Rust core (`sase-core-rs`); image bytes
  could be loaded/scaled there for speed. Out of scope here, but worth a
  follow-up if PDF rendering shows up in profiles.

---

## 11. Suggested next-step shape (for a future plan)

Not a plan — just the obvious factoring if/when we implement:

1. `sase.tui.graphics.capabilities` — startup probe, `Capabilities`
   dataclass, env-var fast paths, tmux/SSH heuristics. Wire the probe from
   `src/sase/main/ace_handler.py` before `app.run()`.
2. `sase.tui.graphics.tgp` — TGP encoder (upload, virtual placement,
   delete, placeholder cell generation). Implement from Kitty's spec or lift
   only license-compatible code, with tmux passthrough wrapping.
3. `sase.tui.graphics.fallback` — halfblock encoder (chafa shell-out or
   pure-Python). Returns a `Strip` directly.
4. `sase.tui.widgets.image_view` — Textual widget composing the above,
   modeled on `textual-imageview`'s pan/zoom keymap.
5. `sase.tui.widgets.pdf_view` — wraps `pypdfium2` page rendering, lazy
   render + LRU + background prefetch, delegates display to `image_view`.
6. Wire into the smallest-blast-radius use case first (probably notification
   attachments) before threading through ChangeSpec / xprompt catalog.

---

## Sources

- [Kitty graphics protocol spec](https://sw.kovidgoyal.net/kitty/graphics-protocol/)
- [Unicode placeholders section](https://sw.kovidgoyal.net/kitty/graphics-protocol/#unicode-placeholders)
- [Discussion #4021 — Unicode placeholder origin PoC](https://github.com/kovidgoyal/kitty/discussions/4021)
- [`kitten icat` docs](https://sw.kovidgoyal.net/kitty/kittens/icat/) and [source](https://github.com/kovidgoyal/kitty/blob/master/kittens/icat/main.py)
- [`kitten ssh` docs](https://sw.kovidgoyal.net/kitty/kittens/ssh/) and [Kitty FAQ](https://sw.kovidgoyal.net/kitty/faq/)
- [tmux manual: `allow-passthrough`](https://man7.org/linux/man-pages/man1/tmux.1.html)
- [Are We Sixel Yet?](https://www.arewesixelyet.com/)
- [Ghostty feature docs](https://ghostty.org/docs/features)
- [WezTerm Kitty image protocol tracking issue](https://github.com/wezterm/wezterm/issues/986)
- [iTerm2 inline images protocol](https://iterm2.com/documentation-images.html)
- [Akmatori — Terminal graphics protocols overview](https://akmatori.com/blog/terminal-graphics-protocols)
- [tmux allow-passthrough notes](https://tmuxai.dev/tmux-allow-passthrough/)
- Kitty issue [#2457](https://github.com/kovidgoyal/kitty/issues/2457) and opentui issue [#334](https://github.com/anomalyco/opentui/issues/334) — tmux/SSH detection edge cases
- [CSI 14t / 16t pixel queries](https://terminalguide.namepad.de/seq/csi_st-14/) and [Kitty discussion #5287](https://github.com/kovidgoyal/kitty/discussions/5287)
- [`textual-image`](https://github.com/lnqs/textual-image), [`textual-image` PyPI metadata](https://pypi.org/project/textual-image/), [`textual-kitty`](https://pypi.org/project/textual-kitty/), [`textual-imageview`](https://github.com/adamviola/textual-imageview), [`term-image`](https://pypi.org/project/term-image/)
- [Rich images discussion #384](https://github.com/Textualize/rich/discussions/384), [Textual Strip API](https://textual.textualize.io/api/strip/)
- [`chafa`](https://github.com/hpjansson/chafa) and [`chafa.py`](https://github.com/GuardKenzie/chafa.py), [`viu`](https://github.com/atanunq/viu), [`viuer`](https://docs.rs/viuer), [`timg`](https://github.com/hzeller/timg)
- [`pypdfium2`](https://pypi.org/project/pypdfium2/), [`pypdfium2` Python API](https://pypdfium2.readthedocs.io/en/stable/python_api.html), [PyMuPDF licensing discussion](https://github.com/pymupdf/PyMuPDF/discussions/971), [Python PDF ecosystem 2024](https://martinthoma.medium.com/the-python-pdf-ecosystem-in-2024-2cad87732e49)
