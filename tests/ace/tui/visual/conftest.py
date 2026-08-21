"""Pytest fixtures for ACE visual regression tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
import time

import pytest

from tests._prettier_fakes import fake_prettier_missing, hide_prettier_from_path
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.visual.renderer_env import assert_renderer_environment

_FIXED_VISUAL_NOW = datetime(2026, 7, 6, 12, 0, 0)


@pytest.fixture(scope="session", autouse=True)
def _require_pinned_renderer_environment(request: pytest.FixtureRequest) -> None:
    """Fail once before snapshots run when the renderer fingerprint is skewed."""
    assert_renderer_environment(
        update=bool(request.config.getoption("--sase-update-visual-snapshots"))
    )


@pytest.fixture(autouse=True)
def _force_color_for_visual_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    # Rich derives syntax line-number colors from the terminal color system.
    # Pin its truecolor path so neither the caller's terminal nor CI changes
    # the committed rendering, and remove overrides that would defeat it.
    try:
        with monkeypatch.context() as visual_env:
            visual_env.setenv("COLORTERM", "truecolor")
            visual_env.setenv("TERM", "xterm-256color")
            visual_env.delenv("FORCE_COLOR", raising=False)
            visual_env.delenv("NO_COLOR", raising=False)

            # Snapshot captures target the resting state, never an animated
            # intermediate. Textual evaluates this environment variable into
            # a module-level constant at import time, before fixtures run, so
            # pin both forms before each AceApp is constructed.
            visual_env.setenv("TEXTUAL_ANIMATIONS", "none")
            visual_env.setattr("textual.constants.TEXTUAL_ANIMATIONS", "none")

            # Pin the process timezone as well as application-level clocks.
            # ``tzset`` updates libc's cached timezone after both setup and the
            # environment restoration performed when this context exits.
            visual_env.setenv("TZ", "UTC")
            time.tzset()

            # Prompt rendering must not depend on whether the host has prettier on PATH.
            hide_prettier_from_path(visual_env, stub_dir=tmp_path / "hide-prettier")
            fake_prettier_missing(visual_env)
            # Pin the app version so the "sase ace (v…)" header title is byte-stable
            # across runs and install shapes. AceApp seeds the title from
            # ``initial_app_version()`` in ``__init__`` and refines it off-thread from
            # ``resolved_app_version()`` in ``on_mount``; pinning both to the same value
            # keeps the title fixed and prevents the async refinement from changing it
            # mid-capture.
            visual_env.setattr(
                "sase.ace.tui.util.app_version.initial_app_version", lambda: "0.7.1"
            )
            visual_env.setattr(
                "sase.ace.tui.util.app_version.resolved_app_version", lambda: "0.7.1"
            )
            yield
    finally:
        time.tzset()


@pytest.fixture(autouse=True)
def _pin_agent_list_clock_for_visual_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep date-sensitive agent-list runtime text stable in PNG snapshots."""

    def fixed_now() -> datetime:
        return _FIXED_VISUAL_NOW

    for target in (
        "sase.core.time.local_now",
        "sase.ace.tui.actions.agents._display_panel_patches.local_now",
        "sase.ace.tui.actions.agents._loading_compute_finalize.local_now",
        "sase.ace.tui.actions.agents._loading_finalize.local_now",
        "sase.ace.tui.models.agent_groups._keys.local_now",
        "sase.ace.tui.models.agent_groups._tree.local_now",
        "sase.ace.tui.models.agent_time.local_now",
        "sase.ace.tui.models.patch_groups._tree.local_now",
        "sase.ace.tui.modals.logs_pane_render.local_now",
    ):
        monkeypatch.setattr(target, fixed_now)


@pytest.fixture(autouse=True)
def _stub_projects_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Projects-tab snapshots off the real projects directory.

    The pane is lazy now, but dedicated Projects snapshots still need a
    deterministic default that their richer fixtures can override.
    """
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [],
    )
    from sase.repo_inventory import RepoInventory
    from sase.workspace_provider.inventory import WorkspaceInventory

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_repo_inventory",
        lambda *_a, **_kw: RepoInventory(()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_workspace_inventory",
        lambda *_a, **_kw: WorkspaceInventory((), ()),
    )


@pytest.fixture(autouse=True)
def _stub_plugin_incoming_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep visual snapshots from shelling out to ``gh api``."""
    from sase.ace.tui.modals import plugins_browser_pane as pbp
    from sase.updates.incoming_commits import RepoIncomingCommits
    from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
        _visual_incoming_commits,
    )

    monkeypatch.setattr(
        pbp,
        "_fetch_incoming_commits",
        lambda *_a, **_kw: _visual_incoming_commits("plugin"),
    )
    monkeypatch.setattr(
        pbp,
        "_fetch_incoming_commit_groups",
        lambda specs, **_kw: tuple(
            RepoIncomingCommits(label, _visual_incoming_commits(label))
            for label, _spec in specs
        ),
    )


def _visual_artifact_root(config: pytest.Config) -> Path:
    """Return the configured artifact path anchored to pytest's root."""
    artifact_root = Path(config.getoption("--sase-visual-artifact-dir")).expanduser()
    rootpath = config.rootpath
    repo_root = Path(rootpath) if rootpath is not None else Path.cwd()
    if not artifact_root.is_absolute():
        artifact_root = repo_root / artifact_root
    return artifact_root


@pytest.fixture
def ace_png_visual(
    request: pytest.FixtureRequest,
) -> AcePngSnapshotFixture:
    """ACE PNG visual snapshot assertion helper."""
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
