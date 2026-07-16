"""Artifact-change dirty flag routing tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sase.ace.tui.actions._event_refresh import (
    AGENT_ARTIFACT_DELTA_QUEUE_LIMIT,
)
from sase.ace.tui.widgets.changespec_list import ChangeSpecList

from ._event_handlers_dirty_flags_helpers import _FakeApp


def test_artifact_change_marks_all_surfaces_dirty() -> None:
    """A coalesced inotify burst flips every dirty flag."""
    app = _FakeApp(watcher_active=True)
    app._on_artifact_change()
    assert app._dirty_changespecs is True
    assert app._dirty_agents is True
    assert app._dirty_axe is True
    assert app.refresh_calls == ["schedule_changespecs"]


def test_artifact_change_marks_only_agents_dirty_for_done_marker() -> None:
    app = _FakeApp(watcher_active=True)
    path = Path.home() / ".sase" / "projects" / "sase" / "artifacts" / "a" / "done.json"

    app._on_artifact_change((path,))

    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == (path.parent,)
    assert app._dirty_agent_artifact_fallback_reason is None
    assert app._dirty_changespecs is False
    assert app.refresh_calls == []


@pytest.mark.parametrize(
    "marker_name",
    ["workflow_state.json", "prompt_step_001.json"],
)
def test_artifact_change_marks_agents_dirty_for_loader_visible_markers(
    marker_name: str,
) -> None:
    app = _FakeApp(watcher_active=True)
    path = (
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
        / marker_name
    )

    app._on_artifact_change((path,))

    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == (path.parent,)
    assert app._dirty_changespecs is False
    assert app.refresh_calls == []


@pytest.mark.asyncio
async def test_known_marker_change_schedules_artifact_delta_not_broad_load() -> None:
    app = _FakeApp(watcher_active=True)
    path = (
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
        / "done.json"
    )

    app._on_artifact_change((path,))
    await app._run_auto_refresh()

    assert app.refresh_calls == ["delta:watcher:1"]
    assert app.delta_requests == [("watcher", (path.parent,))]
    assert app._dirty_agents is False
    assert app._dirty_agent_artifact_dirs == ()
    assert app._dirty_agent_artifact_fallback_reason is None


@pytest.mark.asyncio
async def test_artifact_month_shard_path_uses_broad_auto_refresh_fallback() -> None:
    app = _FakeApp(watcher_active=True)
    path = (
        Path.home() / ".sase" / "projects" / "sase" / "artifacts" / "ace-run" / "202605"
    )

    app._on_artifact_change((path,))
    await app._run_auto_refresh()

    assert app.refresh_calls == ["agents"]
    assert app.delta_requests == []
    assert app._dirty_agent_artifact_dirs == ()
    assert app._dirty_agent_artifact_fallback_reason is None
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "unknown_watcher_path"
    )


@pytest.mark.asyncio
async def test_artifact_delta_queue_overflow_uses_broad_fallback() -> None:
    app = _FakeApp(watcher_active=True)
    paths = tuple(
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / f"20260528{i:06d}"
        / "done.json"
        for i in range(AGENT_ARTIFACT_DELTA_QUEUE_LIMIT + 1)
    )

    app._on_artifact_change(paths)
    await app._run_auto_refresh()

    assert app.refresh_calls == ["agents"]
    assert app.delta_requests == []
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "dirty_queue_overflow"
    )


@pytest.mark.parametrize(
    "path",
    [
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000",
        Path.home() / ".sase" / "projects" / "sase" / "artifacts" / "20260528120000",
    ],
)
def test_artifact_change_marks_agents_dirty_for_likely_agent_root_directory(
    path: Path,
) -> None:
    app = _FakeApp(watcher_active=True)

    app._on_artifact_change((path,))

    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == (path,)
    assert app._dirty_deleted_agent_artifact_dirs == (path,)
    assert app._dirty_agent_artifact_fallback_reason is None
    assert app.refresh_calls == []


@pytest.mark.parametrize(
    "path",
    [
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "202605"
        / "28"
        / "20260528120000",
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "workflow-build"
        / "20260528120000",
    ],
)
@pytest.mark.asyncio
async def test_artifact_dir_deletion_schedules_delta_not_broad_load(
    path: Path,
) -> None:
    app = _FakeApp(watcher_active=True)

    app._on_artifact_change((path,))
    await app._run_auto_refresh()

    assert app.refresh_calls == ["delta:watcher:1"]
    assert app.delta_requests == [("watcher", (path,))]
    assert app._dirty_agent_artifact_fallback_reason is None


def test_existing_moved_artifact_dir_schedules_exact_delta(tmp_path: Path) -> None:
    app = _FakeApp(watcher_active=True)
    path = (
        tmp_path
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "202605"
        / "28"
        / "20260528120000"
    )
    path.mkdir(parents=True)

    app._on_artifact_change((path,))

    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == (path,)
    assert app._dirty_deleted_agent_artifact_dirs == ()
    assert app._dirty_agent_artifact_fallback_reason is None


def test_registered_self_deletion_path_is_dropped() -> None:
    app = _FakeApp(watcher_active=True)
    path = (
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
    )

    app._register_expected_agent_artifact_deletion(path)
    app._on_artifact_change((path,))

    assert app._dirty_agents is False
    assert app._dirty_agent_artifact_dirs == ()
    assert app.refresh_calls == []
    assert app._expected_agent_artifact_deletions == {}


def test_registered_self_deletion_marker_path_is_dropped() -> None:
    app = _FakeApp(watcher_active=True)
    artifacts_dir = (
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
    )

    app._register_expected_agent_artifact_deletion(artifacts_dir)
    app._on_artifact_change((artifacts_dir / "done.json",))

    assert app._dirty_agents is False
    assert app._dirty_agent_artifact_dirs == ()
    assert app.refresh_calls == []


def test_expired_self_deletion_registry_entry_does_not_suppress_path() -> None:
    app = _FakeApp(watcher_active=True)
    path = (
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
    )
    with app._expected_agent_artifact_deletions_lock:
        app._expected_agent_artifact_deletions[str(path)] = time.monotonic() - 1.0

    app._on_artifact_change((path,))

    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == (path,)
    assert app._dirty_deleted_agent_artifact_dirs == (path,)


@pytest.mark.parametrize(
    "path",
    [
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
        / "live_reply.md",
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
        / "generated"
        / "response.md",
    ],
)
def test_artifact_change_ignores_non_loader_artifact_content(path: Path) -> None:
    app = _FakeApp(watcher_active=True)

    app._on_artifact_change((path,))

    assert app._dirty_agents is False
    assert app._dirty_changespecs is False
    assert app._dirty_axe is False
    assert app.refresh_calls == []


def test_artifact_change_mixed_marker_and_content_marks_agents_dirty() -> None:
    app = _FakeApp(watcher_active=True)
    artifacts_dir = (
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
    )

    app._on_artifact_change(
        (
            artifacts_dir / "live_reply.md",
            artifacts_dir / "done.json",
            artifacts_dir / "generated" / "response.md",
        )
    )

    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == (artifacts_dir,)
    assert app.refresh_calls == []


def test_artifact_change_schedules_only_changespecs_for_project_file() -> None:
    app = _FakeApp(watcher_active=True)
    path = Path.home() / ".sase" / "projects" / "sase" / "sase.gp"

    app._on_artifact_change((path,))

    assert app._dirty_changespecs is True
    assert app._dirty_axe is True
    assert app._dirty_agents is False
    assert app.refresh_calls == ["schedule_changespecs"]


def test_artifact_change_schedules_only_changespecs_for_bead_file() -> None:
    app = _FakeApp(watcher_active=True)
    path = Path.cwd() / "sdd" / "beads" / "sase-u.1.md"

    app._on_artifact_change((path,))

    assert app._dirty_changespecs is True
    assert app._dirty_agents is False
    assert app._dirty_axe is False
    assert app.refresh_calls == ["schedule_changespecs"]


def test_artifact_change_uses_cached_sdd_beads_dir_for_local_store(
    tmp_path: Path,
) -> None:
    beads_dir = tmp_path / ".sase" / "sdd" / "beads"
    app = _FakeApp(watcher_active=True, sdd_beads_dir=beads_dir)

    app._on_artifact_change((beads_dir / "issues.jsonl",))

    assert app._dirty_changespecs is True
    assert app._dirty_agents is False
    assert app._dirty_agent_artifact_dirs == ()
    assert app._dirty_axe is False
    assert app.refresh_calls == ["schedule_changespecs"]


def test_artifact_change_does_not_schedule_agent_load_for_notifications() -> None:
    app = _FakeApp(watcher_active=True)
    path = Path.home() / ".sase" / "notifications" / "notification.json"

    app._on_artifact_change((path,))

    assert app._dirty_notifications is True
    assert app._dirty_agents is False
    assert app.refresh_calls == []


def test_selection_navigation_does_not_trigger_refresh_work() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "changespecs"
    app.changespecs = [object()]
    app.current_idx = 0
    event = ChangeSpecList.SelectionChanged(0)

    app.on_change_spec_list_selection_changed(event)

    assert app.refresh_calls == []
