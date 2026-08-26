"""Pytest fixtures for `SasePager` PNG visual regression tests.

Reuses the same pinned renderer stack and PNG diff plumbing as the ACE
visual suite (`tests/ace/tui/visual/png_diff.py`), just pointed at a
pager-owned golden directory — the fixture and its comparison logic are not
ACE-specific, only their existing location is.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import time

import pytest

from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.visual.renderer_env import assert_renderer_environment


@pytest.fixture(scope="session", autouse=True)
def _require_pinned_renderer_environment(request: pytest.FixtureRequest) -> None:
    """Fail once before snapshots run when the renderer fingerprint is skewed."""
    assert_renderer_environment(
        update=bool(request.config.getoption("--sase-update-visual-snapshots"))
    )


@pytest.fixture(autouse=True)
def _force_color_for_visual_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    # Same pins as the ACE visual suite: a fixed truecolor terminal, no
    # animation, and a fixed timezone, so committed PNGs are byte-stable.
    try:
        with monkeypatch.context() as visual_env:
            visual_env.setenv("COLORTERM", "truecolor")
            visual_env.setenv("TERM", "xterm-256color")
            visual_env.delenv("FORCE_COLOR", raising=False)
            visual_env.delenv("NO_COLOR", raising=False)
            visual_env.setenv("TEXTUAL_ANIMATIONS", "none")
            visual_env.setattr("textual.constants.TEXTUAL_ANIMATIONS", "none")
            visual_env.setenv("TZ", "UTC")
            time.tzset()
            yield
    finally:
        time.tzset()


def _visual_artifact_root(config: pytest.Config) -> Path:
    artifact_root = Path(config.getoption("--sase-visual-artifact-dir")).expanduser()
    rootpath = config.rootpath
    repo_root = Path(rootpath) if rootpath is not None else Path.cwd()
    if not artifact_root.is_absolute():
        artifact_root = repo_root / artifact_root
    return artifact_root


@pytest.fixture
def pager_png_visual(request: pytest.FixtureRequest) -> AcePngSnapshotFixture:
    """PNG visual snapshot assertion helper for the standalone pager app."""
    update = bool(request.config.getoption("--sase-update-visual-snapshots"))
    artifact_root = _visual_artifact_root(request.config)
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
