"""Unit tests for the ACE renderer-environment fingerprint."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.ace.tui.visual.renderer_env import (
    RendererEnvironmentError,
    RendererEnvironmentManifest,
    assert_renderer_environment,
)

pytestmark = pytest.mark.visual


def _manifest(font: Path) -> RendererEnvironmentManifest:
    return RendererEnvironmentManifest(
        packages={"textual": "8.0.1"},
        fonts={font.name: hashlib.sha256(font.read_bytes()).hexdigest()},
        python_version="3.12.11",
        platform="Linux-x86_64",
    )


def test_renderer_version_mismatch_has_one_actionable_error(tmp_path: Path) -> None:
    font = tmp_path / "font.ttf"
    font.write_bytes(b"font")

    with pytest.raises(RendererEnvironmentError) as exc_info:
        assert_renderer_environment(
            update=False,
            manifest=_manifest(font),
            package_version=lambda _package: "8.2.8",
            fonts_dir=tmp_path,
        )

    message = str(exc_info.value)
    assert "renderer environment mismatch; snapshots were not run" in message
    assert "package textual: expected 8.0.1, found 8.2.8" in message
    assert "Run `just install-visual`" in message
    assert "snapshot regeneration workflow" in message


def test_golden_regeneration_refuses_a_skewed_fingerprint(tmp_path: Path) -> None:
    font = tmp_path / "font.ttf"
    font.write_bytes(b"font")

    with pytest.raises(RendererEnvironmentError, match="regeneration refused"):
        assert_renderer_environment(
            update=True,
            manifest=_manifest(font),
            package_version=lambda _package: "8.2.8",
            fonts_dir=tmp_path,
        )


def test_golden_regeneration_refuses_non_linux_platform(tmp_path: Path) -> None:
    font = tmp_path / "font.ttf"
    font.write_bytes(b"font")

    with pytest.raises(RendererEnvironmentError, match="generated on Linux"):
        assert_renderer_environment(
            update=True,
            manifest=_manifest(font),
            package_version=lambda _package: "8.0.1",
            fonts_dir=tmp_path,
            platform_system=lambda: "Darwin",
            platform_machine=lambda: "arm64",
        )


def test_matching_linux_environment_allows_regeneration(tmp_path: Path) -> None:
    font = tmp_path / "font.ttf"
    font.write_bytes(b"font")

    assert_renderer_environment(
        update=True,
        manifest=_manifest(font),
        package_version=lambda _package: "8.0.1",
        fonts_dir=tmp_path,
        platform_system=lambda: "Linux",
        platform_machine=lambda: "x86_64",
    )
