---
create_time: 2026-05-07 00:24:58
status: done
prompt: sdd/prompts/202605/image_rendering.md
---
# Improve SASE Image Rendering

## Goal

Make image attachments inspectable inside ACE/Textual panels on ordinary terminals, while preserving the existing
high-fidelity Kitty path for users whose terminal stack supports it. The first user-visible win should be that PNG,
JPEG, WebP, and GIF attachments show a bounded preview in both the Agents tab file panel and the notification modal even
when Kitty graphics probing fails, when running inside tmux, or when using WezTerm/iTerm2/non-Kitty terminals.

## Context

SASE currently treats image attachments as first-class agent artifacts:

- completion records image paths in `done.json.image_paths`;
- completed agents expose those paths through `Agent.extra_files`;
- notification files can include `.png`, `.jpg`, `.jpeg`, `.webp`, and `.gif`;
- the Agents tab file panel and notification modal route supported image paths through
  `src/sase/ace/tui/graphics/image_preview()`.

The rendering implementation is narrower than the attachment contract:

- `GraphicsProtocol` only supports `"kitty"`;
- capability detection actively probes Kitty before `Textual.App.run()`;
- `KittyImageRenderable` uploads PNG bytes and prints Kitty Unicode placeholder cells;
- `INLINE_IMAGE_EXTENSIONS` is PNG-only, so JPEG/WebP/GIF already fall back to text;
- if terminal graphics are unavailable, users only see "preview unavailable" text.

The new research in `sdd/research/202605/textual_image_rendering_research.md` points to the more robust architecture:
make a Rich/Textual-native character-cell renderer the default, then layer native terminal graphics on top
opportunistically.

## Design Principles

1. Prefer a working preview over a high-fidelity preview. A half-block Rich renderable is lower fidelity than Kitty, but
   it survives Textual layout, tmux, SSH, and generic terminal redraws.
2. Keep terminal protocols presentation-only in Python. Per the Rust backend boundary guidance, terminal-specific Rich
   rendering stays in this repo. Shared image attachment discovery already exists elsewhere and should not be moved for
   this work.
3. Keep the first implementation synchronous and bounded unless measurements prove it blocks ACE. The renderable should
   cache aggressively and enforce file/pixel limits; background decode can be a follow-up if needed.
4. Avoid LGPL/vendor risk. Do not vendor `textual-image`. Do not add `rich-pixels` or `term-image` before a small
   SASE-owned renderable proves the baseline behavior.
5. Preserve existing tests and public seams. Callers should still use `image_preview(path, capability, columns, rows)`;
   tests that monkeypatch `image_preview` should keep working.

## Phase 1: Portable Cell Preview Baseline

Implement a SASE-owned Rich renderable, likely `CellImageRenderable`, under `src/sase/ace/tui/graphics/`.

Behavior:

- load supported raster images through Pillow;
- use the first frame for GIF/WebP/APNG-like inputs and make that explicit in diagnostics only if needed;
- convert to RGBA and composite transparency against a stable dark background;
- preserve aspect ratio within the caller-provided `(columns, rows)` cell bounds;
- resize to `columns x rows*2` image pixels;
- emit one terminal cell per two vertical pixels using the upper-half block character with foreground/background colors;
- use truecolor Rich styles when available, and keep a simple 256-color fallback if `GraphicsCapability.truecolor` is
  false;
- return `ImageFallbackRenderable` with a concise reason for missing files, unsupported formats, Pillow import failure,
  decode errors, or images above configured size/pixel limits.

Dependency decision:

- Add `pillow` as a direct dependency unless the environment strongly objects. ACE is already a TUI-first application
  and image artifacts are now documented behavior; making the baseline preview optional would mean many users keep the
  current broken default.
- If dependency churn is a concern during implementation, structure imports locally so the fallback remains clean and so
  moving Pillow to an optional extra later is straightforward.

Caching and bounds:

- cache rendered line groups by `(absolute_path, mtime_ns, size, columns, rows, truecolor/palette, background)`;
- keep the cache small, for example 64 entries with `functools.lru_cache`;
- clamp preview dimensions through the existing `image_preview_size_for_viewport()` helper;
- add max-file-size and max-pixel-count guardrails so corrupted or huge images do not stall ACE.

Integration:

- Change `image_preview()` selection so unsupported/missing files still fall back, Kitty-supported PNGs can still use
  `KittyImageRenderable`, and every other valid raster image tries `CellImageRenderable` before text fallback.
- Keep `KittyImageRenderable` cleanup tracking unchanged in callers by only storing cleanup state when the selected
  renderable is a Kitty renderable.
- Update fallback copy from "preview unavailable" to distinguish "native graphics unavailable" from "portable preview
  unavailable"; after this phase, native graphics failure alone should not prevent a preview.

## Phase 2: Tests And Documentation

Add focused tests that do not require a real terminal graphics stack:

- image path routing still happens before UTF-8 file reads in the file panel and notification modal;
- PNG with Kitty capability still selects `KittyImageRenderable`;
- JPEG/WebP/GIF with or without Kitty capability select the cell renderable when Pillow can decode them;
- terminal graphics unavailable for PNG selects cell renderable instead of text fallback;
- missing/unsupported/decode-failing files return `ImageFallbackRenderable`;
- half-block rendering respects requested cell dimensions for wide, tall, tiny, and transparent images;
- cache invalidates when mtime or file size changes;
- no renderable emits more text rows than the requested preview rows.

Documentation updates:

- update `docs/agent_images.md` to describe the new portable cell preview as the default and Kitty as an optional native
  upgrade;
- update the `SASE_TUI_GRAPHICS` documentation to clarify that it controls native terminal graphics, not portable cell
  previews;
- remove or revise PNG-only inline-preview language once JPEG/WebP/GIF render through the portable path.

Verification:

- run `just install` first in this workspace if dependencies or the venv may be stale;
- run focused tests under `tests/ace/tui/graphics/` and `tests/ace/tui/test_image_file_panels.py`;
- run `just check` before completion, per repo guidance.

## Phase 3: Renderer Selection Diagnostics

Once the portable baseline works, make renderer decisions easier to diagnose without cluttering the UI:

- introduce a small internal selection result or reason string for `image_preview()`;
- preserve existing public return behavior, but make tests assert selection reasons where useful;
- include reasons such as:
  - `native=kitty selected`;
  - `native=kitty skipped: non-PNG source`;
  - `portable=cell selected`;
  - `portable=cell unavailable: Pillow not installed`;
  - `fallback=text selected`.

This phase should avoid user-visible verbosity unless a preview cannot be rendered.

## Phase 4: Optional Native Protocol Expansion

Only after the portable preview is stable:

- add Pillow-backed PNG normalization for Kitty so JPEG/WebP/GIF can use Kitty in known-good Kitty sessions;
- generalize `GraphicsProtocol = Literal["kitty"]` toward `"kitty" | "iterm2"` and add an iTerm2/WezTerm OSC 1337
  renderable;
- keep native protocols opt-in or easy to disable through `SASE_TUI_GRAPHICS`;
- treat Sixel as a later experiment because the research calls out Textual flicker/performance and tmux build-flag
  complexity.

Native backends must always fall back silently to the portable cell renderer.

## Non-Goals

- Do not add PDF or SVG rasterization in this change.
- Do not implement animation timers for GIF/WebP/APNG yet; first-frame preview is enough.
- Do not replace the existing notification attachment contract.
- Do not move terminal rendering into `sase-core`.
- Do not vendor `textual-image` or add an LGPL dependency as part of the first fix.

## Expected Outcome

After Phase 1 and Phase 2, users can cycle to an attached image in ACE and identify it inside the current panel on any
reasonable terminal. Kitty users may still get native bitmap rendering for PNGs, but a failed Kitty probe, tmux
passthrough issue, or non-PNG image no longer collapses the experience to a text-only placeholder.
