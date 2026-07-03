"""Unit tests for the visual-golden font-pin guard.

These exercise the probe *decision* logic without a real renderer: the probe's
two render results are stubbed, so the tests run in the normal (non-visual) fast
suite and need neither cairosvg nor a font-pin-ignoring host. The subprocess
rendering (:func:`render_probe_under_fontconfig`) is intentionally not exercised
here because it requires a real cairo/fontconfig stack.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ace.tui.visual._font_pin_guard import (
    FontPinIgnoredError,
    build_probe_configs,
    check_font_pin_for_update,
    renders_indicate_pin_honored,
)


def test_renders_indicate_pin_honored_when_bytes_differ() -> None:
    assert renders_indicate_pin_honored(b"fira-code", b"empty") is True


def test_renders_indicate_pin_ignored_when_bytes_identical() -> None:
    assert renders_indicate_pin_honored(b"same", b"same") is False


def test_check_raises_when_renderer_ignores_font_pin(tmp_path: Path) -> None:
    # A renderer that ignores FONTCONFIG_FILE produces identical bytes for both
    # the bundled-fonts config and the empty-fonts config.
    def render_probe(_conf: Path) -> bytes:
        return b"identical-render"

    with pytest.raises(FontPinIgnoredError, match="ignores the bundled-font pin"):
        check_font_pin_for_update(
            fonts_dir=tmp_path / "fonts",
            workdir=tmp_path / "probe",
            render_probe=render_probe,
        )


def test_check_permits_update_when_font_pin_is_honored(tmp_path: Path) -> None:
    # A renderer that honors FONTCONFIG_FILE renders the probe differently under
    # the bundled-fonts config vs. the empty-fonts config.
    def render_probe(conf: Path) -> bytes:
        return str(conf).encode("utf-8")

    check_font_pin_for_update(
        fonts_dir=tmp_path / "fonts",
        workdir=tmp_path / "probe",
        render_probe=render_probe,
    )


def test_check_uses_distinct_bundled_and_empty_font_dirs(tmp_path: Path) -> None:
    seen: list[Path] = []

    def render_probe(conf: Path) -> bytes:
        seen.append(conf)
        return str(conf).encode("utf-8")

    check_font_pin_for_update(
        fonts_dir=tmp_path / "fonts",
        workdir=tmp_path / "probe",
        render_probe=render_probe,
    )

    # The probe renders exactly two configs, and they are distinct files.
    assert len(seen) == 2
    assert seen[0] != seen[1]


def test_build_probe_configs_points_at_bundled_then_empty_dir(tmp_path: Path) -> None:
    fonts_dir = tmp_path / "bundled-fonts"
    fonts_dir.mkdir()
    real_conf, empty_conf = build_probe_configs(fonts_dir, tmp_path / "probe")

    real_text = real_conf.read_text()
    empty_text = empty_conf.read_text()

    # The real config points at the bundled fonts; the empty config points at a
    # freshly created empty directory so a fontconfig-honoring renderer has no
    # font to resolve.
    assert str(fonts_dir) in real_text
    assert str(fonts_dir) not in empty_text
    empty_dir = tmp_path / "probe" / "empty-fonts"
    assert empty_dir.is_dir()
    assert not any(empty_dir.iterdir())
    assert str(empty_dir) in empty_text
