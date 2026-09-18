"""Tests for the post-mount dismissed-projection sync wiring.

Locks in the cold-start contract from
``sdd/plans/202606/fast_ace_tui_startup.md``: ``AceApp.__init__`` never
touches the artifact index or dismissed bundle archive, and the
maintenance sync instead runs as a post-mount background worker that
nudges an agents refresh when the projection actually changed.
"""

from __future__ import annotations

import asyncio
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
    assert isinstance(app._dismissed_proc_shells, set)


def test_start_post_mount_background_loads_schedules_dismissed_sync_once() -> None:
    """The startup launcher chains dismissed sync after agents load."""
    app = AceApp()
    app._mark_startup_on_mount()
    scheduled: list[object] = []

    with (
        patch.object(
            app,
            "run_worker",
            side_effect=lambda fn, **kwargs: scheduled.append(fn),
        ),
        patch.object(app, "_start_post_first_paint_services"),
        patch.object(app, "set_timer"),
        patch.object(app, "_start_artifact_watcher"),
        patch.object(app, "_start_prompt_source_watcher"),
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
async def test_startup_dismissed_sync_waits_for_initial_agents_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dismissed-index maintenance starts only after startup agents load."""
    app = AceApp()
    app._mark_startup_on_mount()
    agent_started = asyncio.Event()
    agent_release = asyncio.Event()
    dismissed_done = asyncio.Event()
    events: list[str] = []
    tasks: list[asyncio.Task[None]] = []

    async def agents() -> None:
        events.append("prepare-start")
        events.append("agents-start")
        agent_started.set()
        await agent_release.wait()
        events.append("agents-complete")
        app._agents_first_load_done = True
        app._mark_startup_agents_ready()
        app._maybe_end_startup_stopwatch()
        callbacks = list(app._agents_refresh_pending_callbacks)
        app._agents_refresh_pending_callbacks.clear()
        for callback in callbacks:
            callback()

    async def axe() -> None:
        events.append("axe-start")

    async def dismissed_sync() -> None:
        events.append("dismissed-start")
        dismissed_done.set()

    async def notifications() -> None:
        app._mount_notification_state_load_done = True
        app._maybe_mark_mount_state_loads_done()

    async def deferred_state() -> None:
        app._mount_deferred_state_load_done = True
        app._maybe_mark_mount_state_loads_done()

    def run_worker(fn, **kwargs) -> None:  # type: ignore[no-untyped-def]
        del kwargs
        tasks.append(asyncio.create_task(fn()))

    monkeypatch.setattr(app, "_start_post_first_paint_services", lambda: None)
    monkeypatch.setattr(app, "run_worker", run_worker)
    monkeypatch.setattr(
        app,
        "_run_agent_index_startup_prepare_and_refresh",
        agents,
    )
    monkeypatch.setattr(app, "_run_axe_startup_init", axe)
    monkeypatch.setattr(app, "_run_dismissed_index_startup_sync", dismissed_sync)
    monkeypatch.setattr(app, "_run_mount_notification_state_loads", notifications)
    monkeypatch.setattr(app, "_run_deferred_mount_state_loads", deferred_state)
    monkeypatch.setattr(app, "_schedule_agents_fold_state_load", lambda: None)
    monkeypatch.setattr(app, "_start_artifact_watcher", lambda: None)
    monkeypatch.setattr(app, "_start_prompt_source_watcher", lambda: None)
    monkeypatch.setattr(
        app,
        "_schedule_deferred_startup_maintenance",
        lambda *, reason: None,
    )
    monkeypatch.setattr(app, "set_timer", lambda *_args, **_kwargs: object())

    app._start_post_mount_background_loads()

    await asyncio.wait_for(agent_started.wait(), timeout=0.2)
    assert "dismissed-start" not in events
    assert events.index("prepare-start") < events.index("agents-start")

    agent_release.set()
    await asyncio.wait_for(dismissed_done.wait(), timeout=1.0)

    assert events.index("agents-complete") < events.index("dismissed-start")
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)


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
