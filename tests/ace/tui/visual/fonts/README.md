# Bundled fonts for ACE visual snapshot tests

The PNG snapshot suite renders SVG through resvg (`resvg_py`), a pure-Rust rasterizer with its own font database. It is
pointed at this directory via `font_dirs` with `skip_system_fonts=True`, so only these files participate in rendering —
no platform font stack is consulted. Small cross-host edge-rasterization differences are bounded by both area and
alpha-aware color intensity; see the Visual Snapshot Workflow in `docs/development.md` for the comparison contract.

`tests/ace/tui/visual/png_diff.py::render_svg_to_png` maps every generic family (monospace/sans-serif/serif and the
default) to Fira Code, so all text resolves here regardless of the font family Textual emits.

## Files

- `FiraCode-Regular.ttf`, `FiraCode-Bold.ttf` — Fira Code 6.2 (https://github.com/tonsky/FiraCode/releases/tag/6.2),
  licensed under SIL Open Font License 1.1. Replacing these files requires regenerating the goldens with
  `just test-visual -- --sase-update-visual-snapshots`.
