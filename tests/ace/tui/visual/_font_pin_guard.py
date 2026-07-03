"""Guard against regenerating visual goldens on renderers that ignore the pin.

The PNG snapshot suite pins rasterization by exporting a hermetic
``FONTCONFIG_FILE`` that resolves every family to the bundled Fira Code (see
:func:`tests.ace.tui.visual.conftest._hermetic_fontconfig`). That pin only works
on renderers that route font resolution through fontconfig (Linux / CI). On
hosts whose cairo build resolves fonts through a different backend
(macOS / Quartz), ``FONTCONFIG_FILE`` is silently ignored and the produced PNGs
use whatever system font the host happens to have. Goldens regenerated on such a
host are not reproducible by CI and corrupt the corpus (box-drawing glyphs
render as tofu squares, the ``->`` arrow drops out, body text falls back to a
proportional font, etc.).

This module provides a *functional* probe: render a tiny SVG twice, once through
a fontconfig that points at the bundled fonts and once through a fontconfig that
points at an empty directory. A renderer that honors the pin produces different
bytes (real glyphs vs. missing glyphs); a renderer that ignores it produces
byte-identical output. The probe is preferred over a ``sys.platform == "darwin"``
check because it also catches misconfigured Linux hosts and automatically
un-blocks macOS if a future cairo honors fontconfig there.

The probe only runs when ``--sase-update-visual-snapshots`` is passed; normal
comparison runs are untouched.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from collections.abc import Callable

# A short probe including a box-drawing glyph (``─`` renders as a continuous
# line in Fira Code but as tofu / nothing without a resolved font), the ``→``
# arrow that corrupts in the real failure, and a couple of letterforms. The exact
# content only needs to differ between "resolved to Fira Code" and "no font".
PROBE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="48">'
    '<rect width="160" height="48" fill="black"/>'
    '<text x="4" y="32" font-family="monospace" font-size="24" fill="white">'
    "─Ag→B─"
    "</text>"
    "</svg>"
)

# Rasterize the probe SVG read from stdin and emit the PNG bytes on stdout. Run
# in a fresh interpreter so fontconfig initializes against the process's
# ``FONTCONFIG_FILE`` instead of a cached configuration from an earlier render.
_SUBPROCESS_RENDER_SRC = (
    "import sys, cairosvg; "
    "sys.stdout.buffer.write("
    "cairosvg.svg2png(bytestring=sys.stdin.buffer.read()))"
)

_FONT_PIN_IGNORED_MESSAGE = (
    "Cannot regenerate ACE visual snapshot goldens on this host: the renderer "
    "ignores the bundled-font pin (FONTCONFIG_FILE), so the PNGs it produces are "
    "not reproducible by CI and would corrupt the golden corpus (for example, "
    "box-drawing borders render as tofu squares). This is the macOS / Quartz "
    "cairo case.\n"
    "\n"
    "Committed goldens are canonical to the CI (Linux / fontconfig) renderer. To "
    "adopt a golden change from a host like this one:\n"
    "  1. Push the change and let CI run the visual-test job.\n"
    "  2. gh run download <run-id> --name ace-visual-artifacts\n"
    "  3. Inspect each failing test's actual.png, then copy it over the matching "
    "golden under tests/ace/tui/visual/snapshots/png/.\n"
    "\n"
    "See docs/development.md, section 'Visual Snapshot Workflow', for details."
)


class FontPinIgnoredError(RuntimeError):
    """Raised when the host renderer ignores the fontconfig font pin."""


def renders_indicate_pin_honored(real_render: bytes, empty_render: bytes) -> bool:
    """Return whether the two probe renders show the font pin is honored.

    The pin is honored exactly when swapping the font directory (bundled Fira
    Code vs. an empty directory) changes the rendered bytes. A renderer that
    ignores ``FONTCONFIG_FILE`` produces byte-identical output for both configs.
    """
    return real_render != empty_render


def _write_probe_fontconfig(work: Path, fonts_dir: Path) -> Path:
    """Write a hermetic ``fonts.conf`` under *work* pointing at *fonts_dir*."""
    work.mkdir(parents=True, exist_ok=True)
    cache = work / "cache"
    cache.mkdir(exist_ok=True)
    conf = work / "fonts.conf"
    conf.write_text(
        f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{fonts_dir}</dir>
  <cachedir>{cache}</cachedir>
  <alias><family>monospace</family><prefer><family>Fira Code</family></prefer></alias>
  <alias><family>sans-serif</family><prefer><family>Fira Code</family></prefer></alias>
  <alias><family>serif</family><prefer><family>Fira Code</family></prefer></alias>
</fontconfig>
"""
    )
    return conf


def build_probe_configs(fonts_dir: Path, workdir: Path) -> tuple[Path, Path]:
    """Return ``(real_conf, empty_conf)`` probe fontconfig files.

    *real_conf* points at *fonts_dir* (the bundled Fira Code). *empty_conf*
    points at an empty directory, so a fontconfig-honoring renderer has no font
    to resolve and produces visibly different output.
    """
    real_conf = _write_probe_fontconfig(workdir / "real", fonts_dir)
    empty_fonts = workdir / "empty-fonts"
    empty_fonts.mkdir(parents=True, exist_ok=True)
    empty_conf = _write_probe_fontconfig(workdir / "empty", empty_fonts)
    return real_conf, empty_conf


def render_probe_under_fontconfig(conf_path: Path) -> bytes:
    """Rasterize the probe SVG with ``FONTCONFIG_FILE=conf_path`` in a subprocess.

    A subprocess is used because fontconfig caches its configuration for the
    lifetime of a process; rendering both probe variants in-process would reuse
    the first config and defeat the probe.
    """
    env = dict(os.environ)
    env["FONTCONFIG_FILE"] = str(conf_path)
    result = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_RENDER_SRC],
        input=PROBE_SVG.encode("utf-8"),
        env=env,
        capture_output=True,
    )
    return result.stdout


def check_font_pin_for_update(
    *,
    fonts_dir: Path,
    workdir: Path,
    render_probe: Callable[[Path], bytes] = render_probe_under_fontconfig,
) -> None:
    """Raise :class:`FontPinIgnoredError` if the renderer ignores the font pin.

    Renders the probe under a bundled-fonts config and an empty-fonts config and
    compares the results. *render_probe* is injectable so the decision can be
    exercised without a real renderer.
    """
    real_conf, empty_conf = build_probe_configs(fonts_dir, workdir)
    real_render = render_probe(real_conf)
    empty_render = render_probe(empty_conf)
    if not renders_indicate_pin_honored(real_render, empty_render):
        raise FontPinIgnoredError(_FONT_PIN_IGNORED_MESSAGE)
