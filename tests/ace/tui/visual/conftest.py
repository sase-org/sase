"""Pytest fixtures for ACE visual regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ace.tui.visual.svg_snapshot import AceSvgSnapshotFixture


@pytest.fixture
def ace_visual(request: pytest.FixtureRequest) -> AceSvgSnapshotFixture:
    """ACE visual snapshot assertion helper."""
    update = bool(request.config.getoption("--sase-update-visual-snapshots"))
    artifact_root = Path(
        request.config.getoption("--sase-visual-artifact-dir")
    ).expanduser()
    return AceSvgSnapshotFixture(
        snapshot_root=Path(__file__).parent / "snapshots" / "svg",
        artifact_root=artifact_root,
        update=update,
        node_id=request.node.nodeid,
    )
