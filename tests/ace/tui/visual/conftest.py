"""Pytest fixtures for ACE visual regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

_FONTS_DIR = Path(__file__).parent / "fonts"


@pytest.fixture(scope="session")
def _hermetic_fontconfig(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a hermetic fontconfig file pointing only at bundled fonts.

    The PNG snapshot suite renders SVG via cairosvg → cairo → pango → fontconfig.
    Without pinning, the rendered output depends on whatever monospace font
    fontconfig happens to resolve on each host (CI vs. dev machines disagree).
    Bundling Fira Code in-tree and forcing fontconfig to use only that font
    gives byte-identical PNGs everywhere.
    """
    work = tmp_path_factory.mktemp("fontconfig")
    cache = work / "cache"
    cache.mkdir()
    conf = work / "fonts.conf"
    conf.write_text(
        f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{_FONTS_DIR}</dir>
  <cachedir>{cache}</cachedir>
  <alias><family>monospace</family><prefer><family>Fira Code</family></prefer></alias>
  <alias><family>sans-serif</family><prefer><family>Fira Code</family></prefer></alias>
  <alias><family>serif</family><prefer><family>Fira Code</family></prefer></alias>
  <alias><family>arial</family><prefer><family>Fira Code</family></prefer></alias>
</fontconfig>
"""
    )
    return conf


@pytest.fixture(autouse=True)
def _force_color_for_visual_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    _hermetic_fontconfig: Path,
) -> None:
    # Visual snapshots pin Textual's colored output. A NO_COLOR=1 inherited
    # from the caller's shell would otherwise force grayscale rendering and
    # cause every snapshot to diff against the committed golden.
    monkeypatch.delenv("NO_COLOR", raising=False)
    # Pin fontconfig to the bundled Fira Code so PNG rasterization is
    # deterministic regardless of host font configuration.
    monkeypatch.setenv("FONTCONFIG_FILE", str(_hermetic_fontconfig))
    # Pin os.getpid so the "sase ace (PID: …)" header title is byte-stable
    # across runs. AceApp.__init__ sets self.title = f"sase ace (PID: {os.getpid()})".
    import os

    monkeypatch.setattr(os, "getpid", lambda: 12345)


@pytest.fixture(autouse=True)
def _stub_projects_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the always-mounted Projects pane off the real projects directory.

    The Config Center composes its Projects pane in every screenshot even
    when that tab is hidden, so the pane constructor would otherwise read the
    real ``~/.sase/projects`` store and render non-deterministic (or
    "Load failed") content. Patching the symbol the pane imports keeps the
    old standalone project-management snapshots untouched (they stub
    ``project_management_modal.list_project_records`` instead).
    """
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [],
    )


@pytest.fixture
def ace_png_visual(request: pytest.FixtureRequest) -> AcePngSnapshotFixture:
    """ACE PNG visual snapshot assertion helper."""
    update = bool(request.config.getoption("--sase-update-visual-snapshots"))
    artifact_root = Path(
        request.config.getoption("--sase-visual-artifact-dir")
    ).expanduser()
    rootpath = request.config.rootpath
    repo_root = Path(rootpath) if rootpath is not None else Path.cwd()
    location = request.node.location
    test_file = str(location[0]) if location[0] is not None else None
    test_line = location[1] + 1 if location[1] is not None else None
    return AcePngSnapshotFixture(
        snapshot_root=Path(__file__).parent / "snapshots" / "png",
        artifact_root=artifact_root,
        update=update,
        node_id=request.node.nodeid,
        test_file=test_file,
        test_line=test_line,
        repo_root=repo_root,
    )
