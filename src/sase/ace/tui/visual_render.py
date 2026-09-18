"""Canonical SVG-to-PNG rasterization for ACE/TUI visual captures."""

from __future__ import annotations

from pathlib import Path

_BUNDLED_FONTS_DIR = Path(__file__).with_name("fonts")


def _bundled_fonts_dir() -> Path:
    """Return the directory containing the bundled renderer fonts."""
    return _BUNDLED_FONTS_DIR


def _bundled_font_files(fonts_dir: Path | None = None) -> list[str]:
    """Return paths to every bundled renderer face."""
    root = fonts_dir or _BUNDLED_FONTS_DIR
    return sorted(
        str(path)
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in {".otf", ".ttf"}
    )


def render_svg_to_png(svg: str) -> bytes:
    """Render SVG text to PNG bytes using the pinned hermetic renderer.

    Rendering goes through resvg (a pure-Rust SVG rasterizer with its own font
    database) restricted to the bundled fonts. ``skip_system_fonts`` keeps
    every platform text and graphics stack out of the render. Naming Fira Code
    for every generic family gives it every glyph it carries; resvg falls back
    within the bundled database only for a codepoint Fira Code lacks, which is
    how symbol marks such as notification tab icons rasterize as themselves
    instead of ``.notdef`` boxes. ``font_files`` lists those faces explicitly
    because some ``resvg-py`` wheels never scan ``font_dirs``.
    """
    try:
        import resvg_py
    except ImportError as exc:
        raise RuntimeError(
            "ACE SVG-to-PNG rendering could not import resvg_py. "
            "The SASE installation is incomplete or stale. Run `sase update`, "
            "or reinstall the Python environment that owns the `sase` entry "
            "point."
        ) from exc

    fonts_dir = _bundled_fonts_dir()
    return bytes(
        resvg_py.svg_to_bytes(
            svg_string=svg,
            skip_system_fonts=True,
            font_dirs=[str(fonts_dir)],
            # Some resvg-py wheels ignore font_dirs (CPython 3.14 manylinux).
            # Listing faces makes Noto Emoji / DejaVu load on every wheel.
            font_files=_bundled_font_files(fonts_dir),
            font_family="Fira Code",
            monospace_family="Fira Code",
            sans_serif_family="Fira Code",
            serif_family="Fira Code",
        )
    )
