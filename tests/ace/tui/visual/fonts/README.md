# Bundled fonts for ACE visual snapshot tests

The PNG snapshot suite renders SVG via cairosvg, which goes through cairo → pango → fontconfig. Without pinning, the
rendered text depends on whatever "Fira Code, monospace" resolves to on each host, so CI and dev machines disagree on
glyph metrics and the goldens diverge.

`tests/ace/tui/visual/conftest.py` builds a per-session `fonts.conf` that points fontconfig at this directory and
aliases monospace/sans/serif/arial to Fira Code, giving byte-identical PNGs everywhere.

## Files

- `FiraCode-Regular.ttf`, `FiraCode-Bold.ttf` — Fira Code 6.2 (https://github.com/tonsky/FiraCode/releases/tag/6.2),
  licensed under SIL Open Font License 1.1. Replacing these files requires regenerating the goldens with
  `just test-visual -- --sase-update-visual-snapshots`.
