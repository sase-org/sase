"""Pytest fixtures for ACE visual regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture


@pytest.fixture(autouse=True)
def _force_color_for_visual_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Visual snapshots pin Textual's colored output. A NO_COLOR=1 inherited
    # from the caller's shell would otherwise force grayscale rendering and
    # cause every snapshot to diff against the committed golden.
    monkeypatch.delenv("NO_COLOR", raising=False)


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
