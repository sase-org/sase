"""Tests for the post-mount dismissed-projection sync wiring.

Locks in the cold-start contract from
``sdd/tales/202606/fast_ace_tui_startup.md``: ``AceApp.__init__`` never
touches the artifact index or dismissed bundle archive, and the
maintenance sync instead runs as a post-mount background worker that
nudges an agents refresh when the projection actually changed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.core.agent_artifact_index_lifecycle import DismissedProjectionSyncReport
from sase.ace.tui.app import AceApp


def _fail(*args: object, **kwargs: object) -> object:
    raise AssertionError("cold-start init must not touch the artifact index")


def test_init_app_state_performs_no_sync_and_no_bundle_reads(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """``AceApp.__init__`` must not sync the index or parse bundle JSON."""
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.sync_dismissed_agent_artifact_index",
        _fail,
    )
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "sync_dismissed_agent_artifact_index_report",
        _fail,
    )
    monkeypatch.setattr("sase.ace.dismissed_bundle_index._api.read_bundle", _fail)
    monkeypatch.setattr("sase.ace.dismissed_bundle_index._schema.read_bundle", _fail)

    app = AceApp()

    assert app._dismissed_agents_disk_signature_initialized is True


def test_start_post_mount_background_loads_schedules_dismissed_sync_once() -> None:
    """The startup launcher schedules the dismissed-index sync exactly once."""
    app = AceApp()
    scheduled: list[object] = []

    with patch.object(
        app,
        "run_worker",
        side_effect=lambda fn, **kwargs: scheduled.append(fn),
    ):
        app._start_post_mount_background_loads()
        app._start_post_mount_background_loads()

    assert scheduled.count(app._run_dismissed_index_startup_sync) == 1


class _SyncHarness:
    """Minimal app stand-in for driving the startup sync worker."""

    def __init__(self) -> None:
        self._dismissed_agents: set[tuple[Any, str, str | None]] = set()
        self.notifications: list[tuple[str, dict[str, Any]]] = []
        self.refresh_sources: list[str] = []

    def notify(self, message: str, **kwargs: Any) -> None:
        self.notifications.append((message, kwargs))

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        self.refresh_sources.append(source)


@pytest.mark.asyncio
async def test_startup_sync_nudges_agents_refresh_when_projection_changed(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    harness = _SyncHarness()
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "sync_dismissed_agent_artifact_index_report",
        lambda dismissed: DismissedProjectionSyncReport(synced=True, changed=True),
    )

    await AceApp._run_dismissed_index_startup_sync(harness)  # type: ignore[arg-type]

    assert harness.refresh_sources == ["dismissed_index_sync"]
    assert harness.notifications == []


@pytest.mark.asyncio
async def test_startup_sync_is_quiet_when_fast_path_hits(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    harness = _SyncHarness()
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "sync_dismissed_agent_artifact_index_report",
        lambda dismissed: DismissedProjectionSyncReport(synced=True, changed=False),
    )

    await AceApp._run_dismissed_index_startup_sync(harness)  # type: ignore[arg-type]

    assert harness.refresh_sources == []
    assert harness.notifications == []


@pytest.mark.asyncio
async def test_startup_sync_surfaces_corruption_heal(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    harness = _SyncHarness()
    quarantined = Path("/tmp/agent_artifact_index.sqlite.corrupt-20260609T000000Z")
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "sync_dismissed_agent_artifact_index_report",
        lambda dismissed: DismissedProjectionSyncReport(
            synced=True,
            changed=True,
            healed=True,
            quarantined_path=quarantined,
        ),
    )

    await AceApp._run_dismissed_index_startup_sync(harness)  # type: ignore[arg-type]

    assert len(harness.notifications) == 1
    message, kwargs = harness.notifications[0]
    assert "corrupt" in message
    assert quarantined.name in message
    assert kwargs.get("severity") == "warning"
    assert harness.refresh_sources == ["dismissed_index_sync"]


@pytest.mark.asyncio
async def test_startup_sync_snapshots_dismissed_set_before_threading(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """The worker passes a snapshot, not the live (mutable) dismissed set."""
    harness = _SyncHarness()
    harness._dismissed_agents = {("run", "cl", "20260101010101")}
    seen: list[object] = []

    def record_sync(dismissed: object) -> DismissedProjectionSyncReport:
        seen.append(dismissed)
        return DismissedProjectionSyncReport(synced=True)

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "sync_dismissed_agent_artifact_index_report",
        record_sync,
    )

    await AceApp._run_dismissed_index_startup_sync(harness)  # type: ignore[arg-type]

    assert seen == [harness._dismissed_agents]
    assert seen[0] is not harness._dismissed_agents
