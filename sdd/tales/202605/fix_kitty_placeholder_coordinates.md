---
create_time: 2026-05-07 11:30:49
status: done
prompt: sdd/prompts/202605/fix_kitty_placeholder_coordinates.md
---
# Fix Kitty Placeholder Image Rendering

## Problem

The tmux/Kitty detection change made `sase ace` select `KittyImageRenderable` for PNG attachments inside tmux. In the
reported snapshot, the TUI now shows a large block of visible placeholder glyphs instead of the image. That means the
native path is being selected, but Kitty is not interpreting the printed placeholder cells as valid image coordinates.

## Diagnosis

The live session matches the detector's success path:

- `TERM=tmux-256color`
- `TERM_PROGRAM=tmux`
- `TMUX=...`
- `tmux display-message -p '#{client_termname}'` returns `xterm-kitty`
- `tmux show -gqv allow-passthrough` returns `all`
- `detect_graphics_capability()` returns `supported=True`, `protocol='kitty'`, `passthrough='tmux'`

The tmux passthrough wrapper itself matches tmux's documented `ESC P tmux; ... ESC \` form, so the most likely failure
is not that the detector sees the wrong outer terminal.

The concrete protocol bug is in `src/sase/ace/tui/graphics/kitty.py`: `_PLACEHOLDER_MARKS` is generated from all Unicode
combining marks with canonical combining class 230. Kitty's graphics protocol does not define row/column marks that way.
Kitty's own documentation says placeholder coordinate `0` is `U+0305` and coordinate `1` is `U+030D`. SASE currently
emits `U+0300` and `U+0301` for those values. As a result, the terminal receives the private-use placeholder character,
but the attached coordinate diacritics do not identify the virtual placement cells, so the placeholder text becomes
visible instead of being replaced by pixels.

A secondary robustness concern is that tmux truecolor/underline-color handling matters because Kitty placeholder image
and placement ids are encoded in SGR color state. This session's tmux has truecolor-related capabilities in `tmux info`,
but tests should still make the required color/coordinate contract explicit.

## Plan

1. Replace the generated placeholder coordinate table with Kitty's protocol table.
   - Add a literal tuple of codepoints from Kitty's `rowcolumn-diacritics.txt` table, starting with `U+0305` for `0` and
     `U+030D` for `1`.
   - Keep `_placeholder_mark()` as the bounds-checking accessor so callers still get a clear error if a future preview
     size exceeds the table.
   - Keep current preview dimensions far below the protocol limit; no sizing changes are needed for this bug.

2. Add tests that would have caught this regression.
   - In `tests/ace/tui/graphics/test_kitty.py`, assert that `placeholder_grid(2, 2)` emits the exact documented
     coordinate marks for cells `(0,0)`, `(0,1)`, `(1,0)`, and `(1,1)`.
   - Add a bounds test at the table edge so future table edits fail loudly.
   - Avoid asserting only "contains placeholder"; assert exact Unicode codepoints.

3. Keep the tmux detector mostly intact.
   - The reported bad output is caused by invalid placeholder cells after the detector enables the native path.
   - Do not revert the tmux metadata support unless verification shows an independent detector issue.
   - Consider improving the capability reason or truecolor signal only if tests reveal that current tmux color handling
     cannot preserve placeholder ids.

4. Verify focused behavior first.
   - Run `just install` if the workspace venv is stale.
   - Run `tests/ace/tui/graphics/test_kitty.py`, `tests/ace/tui/graphics/test_renderable.py`, and
     `tests/ace/tui/graphics/test_capability.py`.
   - Run `tests/ace/tui/test_image_file_panels.py` to cover the notification and file-panel integration.

5. Run repository verification.
   - Run `just fmt` if formatting changes are needed.
   - Run `just check` before finishing because this repo requires it after code changes.

## Expected Outcome

`sase ace` will continue to choose native Kitty graphics inside tmux when the outer terminal and passthrough allow it,
but the placeholder cells will use Kitty's real coordinate diacritics. Kitty should then bind the printed cells to the
uploaded virtual placement and show the PNG instead of rendering a visible block of placeholder glyphs.
