"""Tests for the post-mount dismissed-projection sync wiring.

Locks in the cold-start contract from
``sdd/plans/202606/fast_ace_tui_startup.md``: ``AceApp.__init__`` never
touches the artifact index or dismissed bundle archive, and the
maintenance sync instead runs as a post-mount background worker that
nudges an agents refresh when the projection actually changed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import sase.ace.tui.actions._startup_loads as startup_loads
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
    """The startup launcher chains dismissed sync after agents load."""
    app = AceApp()
    scheduled: list[object] = []

    with patch.object(
        app,
        "run_worker",
        side_effect=lambda fn, **kwargs: scheduled.append(fn),
    ):
        app._start_post_mount_background_loads()
        app._start_post_mount_background_loads()

        assert scheduled.count(app._run_agent_index_startup_prepare_and_refresh) == 1
        assert scheduled.count(app._run_dismissed_index_startup_sync) == 0
        callbacks = list(app._agents_refresh_pending_callbacks)
        assert len(callbacks) == 1
        callbacks[0]()
        assert scheduled.count(app._run_dismissed_index_startup_sync) == 1


@pytest.mark.asyncio
async def test_startup_dismissed_sync_waits_for_initial_agents_refresh() -> None:
    """Dismissed-index maintenance starts only after startup agents load."""

    class _StartupHarness:
        def __init__(self) -> None:
            self._post_mount_background_loads_started = False
            self._agents_refresh_pending_callbacks: list[Callable[[], None]] = []
            self.agent_started = asyncio.Event()
            self.agent_release = asyncio.Event()
            self.dismissed_done = asyncio.Event()
            self.events: list[str] = []
            self.tasks: list[asyncio.Task[None]] = []

        async def _run_agent_index_startup_prepare_and_refresh(self) -> None:
            self.events.append("prepare-start")
            await self._run_agents_async_refresh()

        async def _run_agents_async_refresh(self) -> None:
            self.events.append("agents-start")
            self.agent_started.set()
            await self.agent_release.wait()
            self.events.append("agents-complete")
            callbacks = list(self._agents_refresh_pending_callbacks)
            self._agents_refresh_pending_callbacks.clear()
            for callback in callbacks:
                callback()

        async def _run_axe_startup_init(self) -> None:
            self.events.append("axe-start")

        def _schedule_agents_fold_state_load(self) -> None:
            self.events.append("fold-load-scheduled")

        async def _run_dismissed_index_startup_sync(self) -> None:
            self.events.append("dismissed-start")
            self.dismissed_done.set()

        def run_worker(self, fn, **kwargs) -> None:  # type: ignore[no-untyped-def]
            del kwargs
            self.tasks.append(asyncio.create_task(fn()))

        def _schedule_dismissed_index_startup_sync(self) -> None:
            AceApp._schedule_dismissed_index_startup_sync(self)  # type: ignore[arg-type]

        def _start_artifact_watcher(self) -> None:
            self.events.append("watcher-start")

        def _mark_startup_first_paint(self) -> None:
            pass

    harness = _StartupHarness()
    AceApp._start_post_mount_background_loads(harness)  # type: ignore[arg-type]

    await asyncio.wait_for(harness.agent_started.wait(), timeout=0.2)
    assert "dismissed-start" not in harness.events
    assert harness.events.index("prepare-start") < harness.events.index("agents-start")

    harness.agent_release.set()
    await asyncio.wait_for(harness.dismissed_done.wait(), timeout=0.2)

    assert harness.events.index("agents-complete") < harness.events.index(
        "dismissed-start"
    )
    await asyncio.wait_for(asyncio.gather(*harness.tasks), timeout=0.2)


class _SyncHarness:
    """Minimal app stand-in for driving the startup sync worker."""

    def __init__(self) -> None:
        self._dismissed_agents: set[tuple[Any, str, str | None]] = set()
        self._artifact_index_maintenance_last_mono = 0.0
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
    monkeypatch.setattr(startup_loads.time, "monotonic", lambda: 123.0)
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "sync_dismissed_agent_artifact_index_report",
        lambda dismissed: DismissedProjectionSyncReport(synced=True, changed=False),
    )

    await AceApp._run_dismissed_index_startup_sync(harness)  # type: ignore[arg-type]

    assert harness.refresh_sources == []
    assert harness.notifications == []
    assert harness._artifact_index_maintenance_last_mono == 123.0


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
