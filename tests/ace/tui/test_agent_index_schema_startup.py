"""Regression tests for stale artifact-index startup orchestration."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions._startup_loads import StartupLoadsMixin
from sase.core.agent_artifact_index_lifecycle import _ArtifactIndexSchemaStatus
from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION


class _StartupHarness:
    def __init__(self) -> None:
        self._artifact_index_schema_rebuild_in_flight = False
        self._artifact_index_schema_bypass = False
        self._dismissed_index_sync_pending_after_schema_rebuild = False
        self._agents_history_reconcile_pending = False
        self._agents_history_reconcile_armed_mono = 0.0
        self.events: list[str] = []
        self.scheduled: list[tuple[str, Callable[[], None] | None]] = []
        self.notifications: list[tuple[str, dict[str, Any]]] = []

    async def _run_agents_async_refresh(self) -> None:
        assert self._artifact_index_schema_rebuild_in_flight
        assert self._artifact_index_schema_bypass
        self.events.append("first_load")

    async def _run_agent_index_startup_prepare(self) -> bool:
        self.events.append("rebuild")
        return True

    def _schedule_agents_async_refresh(
        self,
        *,
        source: str,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        self.scheduled.append((source, on_complete))

    def _resume_startup_index_work_after_schema_rebuild(self) -> None:
        self.events.append("resume_index_work")

    def notify(self, message: str, **kwargs: Any) -> None:
        self.notifications.append((message, kwargs))


@pytest.mark.asyncio
async def test_stale_schema_paints_before_rebuild_and_schedules_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _StartupHarness()
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "read_agent_artifact_index_schema_status",
        lambda: _ArtifactIndexSchemaStatus(
            checked=True,
            stale=True,
            stored_schema_version=1,
        ),
    )

    await StartupLoadsMixin._run_agent_index_startup_prepare_and_refresh(harness)

    assert harness.events == ["first_load", "rebuild"]
    assert harness._artifact_index_schema_rebuild_in_flight is False
    assert harness._artifact_index_schema_bypass is False
    assert len(harness.scheduled) == 1
    source, on_complete = harness.scheduled[0]
    assert source == "index_schema_rebuilt"
    assert on_complete is not None
    on_complete()
    assert harness.events == ["first_load", "rebuild", "resume_index_work"]
    assert harness.notifications == []


@pytest.mark.asyncio
async def test_current_schema_loads_without_bypass_or_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _StartupHarness()

    async def load_current_index() -> None:
        assert harness._artifact_index_schema_rebuild_in_flight is False
        assert harness._artifact_index_schema_bypass is False
        harness.events.append("first_load")

    harness._run_agents_async_refresh = load_current_index  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "read_agent_artifact_index_schema_status",
        lambda: _ArtifactIndexSchemaStatus(
            checked=True,
            stale=False,
            stored_schema_version=2,
        ),
    )

    await StartupLoadsMixin._run_agent_index_startup_prepare_and_refresh(harness)

    assert harness.events == ["first_load"]
    assert harness.scheduled == []


@pytest.mark.asyncio
async def test_prepare_accepts_schema_refreshed_by_another_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "refresh_agent_artifact_index_if_schema_stale",
        lambda: SimpleNamespace(
            checked=True,
            refreshed=False,
            stored_schema_version=AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
            rows_indexed=0,
        ),
    )

    assert await StartupLoadsMixin._run_agent_index_startup_prepare(object()) is True


@pytest.mark.asyncio
async def test_failed_rebuild_keeps_index_bypassed_and_arms_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _StartupHarness()

    async def fail_rebuild() -> bool:
        harness.events.append("rebuild")
        return False

    harness._run_agent_index_startup_prepare = fail_rebuild  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "read_agent_artifact_index_schema_status",
        lambda: _ArtifactIndexSchemaStatus(checked=True, stale=True),
    )

    await StartupLoadsMixin._run_agent_index_startup_prepare_and_refresh(harness)

    assert harness.events == ["first_load", "rebuild"]
    assert harness._artifact_index_schema_rebuild_in_flight is False
    assert harness._artifact_index_schema_bypass is True
    assert harness._agents_history_reconcile_pending is True
    assert harness.scheduled == []
    assert "bounded scan" in harness.notifications[0][0]


def test_startup_index_consumers_defer_until_followup_refresh() -> None:
    scheduled_workers: list[object] = []
    resumed: list[str] = []
    harness = SimpleNamespace(
        _artifact_index_schema_rebuild_in_flight=True,
        _artifact_index_schema_bypass=True,
        _dismissed_index_sync_pending_after_schema_rebuild=False,
        _run_dismissed_index_startup_sync=lambda: None,
        run_worker=lambda fn, **kwargs: scheduled_workers.append(fn),
        _resume_artifact_index_maintenance_after_schema_rebuild=lambda: resumed.append(
            "maintenance"
        ),
    )
    harness._schedule_dismissed_index_startup_sync = (  # type: ignore[attr-defined]
        lambda: StartupLoadsMixin._schedule_dismissed_index_startup_sync(harness)
    )

    StartupLoadsMixin._schedule_dismissed_index_startup_sync(harness)

    assert scheduled_workers == []
    assert harness._dismissed_index_sync_pending_after_schema_rebuild is True
    harness._artifact_index_schema_rebuild_in_flight = False
    harness._artifact_index_schema_bypass = False
    StartupLoadsMixin._resume_startup_index_work_after_schema_rebuild(harness)
    assert scheduled_workers == [harness._run_dismissed_index_startup_sync]
    assert resumed == ["maintenance"]
