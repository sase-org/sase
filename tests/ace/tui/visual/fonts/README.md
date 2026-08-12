# Bundled fonts for ACE visual snapshot tests

The PNG snapshot suite renders SVG through resvg (`resvg_py`), a pure-Rust rasterizer
with its own font database. Each file is passed in the explicit `_FONT_FILES` order via
`font_files` with `skip_system_fonts=True`, so only these files participate in rendering
and fallback order does not depend on directory traversal — no platform font stack is
consulted. Comparison is byte-exact by default; explicit area and alpha-aware
color-intensity overrides are available for bounded non-canonical-platform drift. See
the Visual Snapshot Workflow in `docs/development.md` for the comparison and
regeneration contract.

`tests/ace/tui/visual/png_diff.py::render_svg_to_png` maps every generic family
(monospace/sans-serif/serif and the default) to Fira Code, so all text resolves here
regardless of the font family Textual emits. Fira Code stays the named family for every
generic, so it always wins a glyph both fonts carry; resvg only consults the rest of
this directory for a codepoint Fira Code does not have. That per-glyph fallback is what
keeps symbol-only marks — notification tab icons, for one — from rasterizing as
`.notdef` boxes in the goldens while rendering correctly in a real terminal.

## Files

- `FiraCode-Regular.ttf`, `FiraCode-Bold.ttf` — Fira Code 6.2
  (https://github.com/tonsky/FiraCode/releases/tag/6.2), licensed under SIL Open Font
  License 1.1.
- `DejaVuSans.ttf` — DejaVu Sans 2.37
  (https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37), under the
  Bitstream Vera and Arev free-font licenses. Bundled only as the symbol fallback: it
  carries the Miscellaneous Symbols, Dingbats, and Geometric Shapes marks ACE uses as
  icons and Fira Code does not.
- `NotoEmoji-Regular.ttf` — Noto Emoji (Black & White), Google Fonts `METADATA.pb`
  version 3.000
  (https://github.com/google/fonts/blob/2d85e20401920891efb7cd6272d6339685df2820/ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf),
  licensed under the SIL Open Font License 1.1. Google Fonts distributes the built font
  as a `wght 300-700` variable font; this file is the `wght=400` (Regular) static
  instance, produced with `fontTools.varLib.instancer` so no variable-font axis
  participates in rendering. Bundled as the emoji fallback: resvg cannot use a
  color-emoji font (CBDT/COLR bitmap glyphs are not deterministic in this pipeline), and
  this face's glyphs are plain `glyf` outlines, so it rasterizes the same way the other
  bundled fonts do.

Replacing any of these files requires regenerating the goldens with
`just update-visual-snapshots` on Linux and refreshing their hashes in
`renderer_env.json`. `tests/ace/tui/visual/test_tab_icon_glyphs.py` and
`tests/ace/tui/visual/test_emoji_glyphs.py` are the mechanical glyph audits: they fail
if the bundled fonts stop covering an ACE tab icon or an emoji codepoint `src/sase`
actually uses, so a font swap cannot silently reintroduce tofu.
