"""Pytest fixtures for ACE visual regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ace.tui.visual._font_pin_guard import check_font_pin_for_update
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
    # Pin the app version so the "sase ace (v…)" header title is byte-stable
    # across runs and install shapes. AceApp seeds the title from
    # ``initial_app_version()`` in ``__init__`` and refines it off-thread from
    # ``resolved_app_version()`` in ``on_mount``; pinning both to the same value
    # keeps the title fixed and prevents the async refinement from changing it
    # mid-capture.
    monkeypatch.setattr(
        "sase.ace.tui.util.app_version.initial_app_version", lambda: "0.7.1"
    )
    monkeypatch.setattr(
        "sase.ace.tui.util.app_version.resolved_app_version", lambda: "0.7.1"
    )


@pytest.fixture(autouse=True)
def _stub_projects_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the always-mounted Projects pane off the real projects directory.

    The Config Center composes its Projects pane in every screenshot even
    when that tab is hidden, so the pane constructor would otherwise read the
    real ``~/.sase/projects`` store and render non-deterministic (or
    "Load failed") content. Patching the symbol the pane imports keeps every
    Admin Center snapshot deterministic; dedicated Projects-tab snapshots can
    override this stub with their own project records.
    """
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [],
    )


@pytest.fixture(scope="session")
def _visual_snapshot_update_guard(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Block golden updates on renderers that ignore the bundled-font pin.

    Runs lazily, once per session, and only when
    ``--sase-update-visual-snapshots`` is passed and the first visual test would
    write a golden. On a host whose renderer silently ignores ``FONTCONFIG_FILE``
    (macOS / Quartz), regenerating goldens produces fallback-font / tofu PNGs
    that CI cannot reproduce, so the update is refused with an actionable error
    pointing at the CI-artifact adoption workflow. Comparison runs (no update
    flag) are unaffected.
    """
    if not request.config.getoption("--sase-update-visual-snapshots"):
        return
    workdir = tmp_path_factory.mktemp("font-pin-probe")
    check_font_pin_for_update(fonts_dir=_FONTS_DIR, workdir=workdir)


@pytest.fixture
def ace_png_visual(
    request: pytest.FixtureRequest,
    _visual_snapshot_update_guard: None,
) -> AcePngSnapshotFixture:
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
