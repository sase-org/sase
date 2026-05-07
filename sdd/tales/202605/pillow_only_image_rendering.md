---
create_time: 2026-05-07 11:47:17
status: done
prompt: sdd/prompts/202605/pillow_only_image_rendering.md
---
# Remove Native Terminal Image Rendering

## Goal

Make ACE image previews use one rendering strategy everywhere: Pillow decodes raster images, and Rich/Textual paints a
portable half-block cell preview inside the existing panels. Remove native-terminal graphics support and references to
specific terminal families such as Kitty, Ghostty, tmux passthrough, and force-probe configuration.

The intended outcome is boring but reliable: when a supported image attachment is selected, ACE should render it through
the same Pillow-backed path regardless of terminal, tmux, SSH, or environment variables.

## Current State

The image-preview stack lives in `src/sase/ace/tui/graphics/`.

- `cell.py` already implements the desired portable renderer using Pillow, `ImageOps.contain()`, RGBA compositing, and
  Rich half-block segments.
- `renderable.py` chooses between `KittyImageRenderable` for native PNG previews and `CellImageRenderable` as fallback.
- `capability.py` detects native graphics support through environment parsing, tmux metadata, and an optional active
  Kitty probe.
- `kitty.py` contains Kitty protocol upload, placement, deletion, tmux wrapping, placeholder-coordinate code, and image
  ID helpers.
- File-panel and notification-modal code track `KittyImageRenderable` instances so they can emit terminal cleanup escape
  sequences when images change.
- Docs describe `SASE_TUI_GRAPHICS`, Kitty/Ghostty detection, tmux passthrough, and native PNG upgrades.

Pillow is already a direct dependency in `pyproject.toml`, so this change does not need a new dependency.

## Design

Use `CellImageRenderable` as the only real image renderer.

- Keep supported raster extensions as `.png`, `.jpg`, `.jpeg`, `.webp`, and `.gif`.
- Remove the PNG-only "inline native image" distinction.
- Keep the current bounded rendering behavior: first frame only, file-size guard, pixel-count guard, LRU cache,
  caller-provided `(columns, rows)`, aspect-ratio preservation, transparency compositing, truecolor/256-color selection.
- Keep `GraphicsCapability` only if it remains useful as a small color-depth context object for callers. It should no
  longer represent protocol support, terminal family, passthrough, probe state, or native graphics availability.
- Prefer renaming or reshaping public names toward generic image preview terminology when doing so does not create
  unnecessary churn. Backward compatibility inside the repo is less important than removing misleading terminal-specific
  concepts.

The likely simplest shape is:

- Replace `GraphicsCapability` with a small `ImageRenderContext` or simplified capability carrying `truecolor` and a
  reason string.
- Replace `detect_graphics_capability()` with a side-effect-free color-context helper, or remove the pre-run detection
  call entirely and let `CellImageRenderable` infer truecolor from the environment.
- Change `image_preview()` so every valid supported image attempts `CellImageRenderable.from_path()` directly and
  returns `ImageFallbackRenderable` only for unsupported paths, missing files, Pillow import/decode failures, or
  guardrail failures.

## Implementation Plan

1. Simplify the graphics module API.
   - Delete `src/sase/ace/tui/graphics/kitty.py`.
   - Replace `capability.py` with a small terminal-color helper, or fold `has_truecolor()` into
     `cell.py`/`renderable.py`.
   - Remove `INLINE_IMAGE_EXTENSIONS`, `is_inline_image_path()`, `KittyImageRenderable`, `TerminalControlRenderable`,
     Kitty placeholder constants, upload helpers, tmux passthrough helpers, and cleanup sequence APIs from
     `graphics/__init__.py`.

2. Make `image_preview()` Pillow-only.
   - Remove all native-protocol branching in `renderable.py`.
   - Return `CellImageRenderable.from_path()` for every supported existing image extension.
   - Keep `ImageFallbackRenderable` for unsupported extensions, missing files, decode failures, huge images, and missing
     Pillow.
   - Update fallback copy so it says "Image preview unavailable" rather than "Portable image preview unavailable".

3. Remove native cleanup handling from UI surfaces.
   - In `widgets/file_panel/_display.py`, stop importing/storing `KittyImageRenderable` and `TerminalControlRenderable`.
   - Remove `_current_image_renderable` cleanup state or reduce it to no-op state only if class attribute contracts need
     it.
   - Do the same in `modals/notification_modal.py` and `modals/notification_modal_attachments.py`.
   - Keep the panel sizing and "image path before text read" behavior unchanged.

4. Remove ACE startup graphics probing.
   - Stop calling `detect_graphics_capability()` in `src/sase/main/ace_handler.py`.
   - Remove or simplify the `graphics_capability` constructor argument and stored `AceApp.graphics_capability` field.
   - If keeping a color-depth context on the app is useful, construct it without terminal probes and without terminal
     family logic.

5. Rewrite tests around the new contract.
   - Delete or replace `tests/ace/tui/graphics/test_capability.py` and `test_kitty.py`.
   - Update `test_renderable.py` so PNG, JPEG, WebP, and GIF all select `CellImageRenderable`, even with formerly native
     capability inputs removed.
   - Keep tests for dimensions, cache invalidation, missing/unsupported/decode-failing fallback, file-size/pixel
     guardrails if present, and max rendered rows.
   - Update `tests/ace/tui/graphics/test_ace_app_graphics.py` or remove it if app-level graphics state disappears.
   - Update `tests/ace/tui/test_image_file_panels.py` to stop expecting native cleanup state while still proving image
     previews route before text reads.

6. Update documentation and repo references.
   - Rewrite `docs/agent_images.md` to describe only Pillow-backed cell previews.
   - Update `docs/ace.md` and `docs/configuration.md` to remove `SASE_TUI_GRAPHICS`.
   - Search `src`, `tests`, `docs`, `README.md`, and user-facing config for `kitty`, `ghostty`, `tmux passthrough`,
     `SASE_TUI_GRAPHICS`, `native terminal graphics`, and `inline image`; remove or revise current support references.
   - Leave historical SDD/tale documents alone unless they are surfaced as current docs. They are useful project history
     and do not affect runtime behavior.

## Verification

Run focused checks first:

- `pytest tests/ace/tui/graphics tests/ace/tui/test_image_file_panels.py`

Then run repo checks per workspace guidance:

- `just install`
- `just check`

If `just check` is too slow or fails for unrelated existing issues, capture the exact failing command and reason before
handing back.

## Risks And Mitigations

- Detailed text-heavy infographics can look blurry in half-block previews. That is acceptable for this change because
  the requested direction is reliability over native terminal fidelity; users can still open the file in `$EDITOR` or an
  external image viewer from the existing file actions.
- Removing `SASE_TUI_GRAPHICS` is a user-visible config removal. Mitigate by deleting the docs entry and ensuring no
  runtime code reads it.
- Tests may have many Kitty-specific assertions. Treat them as obsolete coverage, not behavior to preserve.
- If `GraphicsCapability` is used outside image rendering, keep a compatibility shim only long enough to avoid broad
  unrelated churn, but do not preserve protocol/terminal-family semantics.

## Non-Goals

- Do not add new native protocols such as iTerm2, Sixel, or WezTerm.
- Do not add animation support for GIF/WebP/APNG.
- Do not add PDF or SVG rasterization.
- Do not move rendering behavior into `sase-core`; this remains Textual/Rich presentation code.
- Do not change image attachment discovery or notification delivery contracts.
