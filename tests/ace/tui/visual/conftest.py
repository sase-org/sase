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


@pytest.fixture
def ace_png_visual(
    request: pytest.FixtureRequest,
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
