"""Scheduling and tracked-task coverage for ACE agents-repository sync."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions import agents_sync
from sase.ace.tui.actions.agents_sync import (
    AgentsSyncActionsMixin,
    initialize_agents_sync_state,
)
from sase.agents_sync.models import (
    CachedIntegrationResult,
    CapturedIncomingHood,
    ProjectSyncStatus,
    SyncOutcome,
    SyncStatusSnapshot,
)


class _Indicator:
    def __init__(self) -> None:
        self.snapshots: list[SyncStatusSnapshot] = []
        self.pending_updates: tuple[CapturedIncomingHood, ...] = ()

    def set_status(self, snapshot: SyncStatusSnapshot) -> None:
        self.snapshots.append(snapshot)
        self.pending_updates = tuple(
            item for status in snapshot.projects for item in status.pending_updates
        )


class _Harness(AgentsSyncActionsMixin):
    def __init__(self) -> None:
        initialize_agents_sync_state(self)
        self.indicator = _Indicator()
        self.intervals: list[tuple[float, Callable[[], None], str]] = []
        self.workers: list[tuple[Callable[[], None], dict[str, object]]] = []
        self.submitted: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        self.refresh_sources: list[str] = []

    def set_interval(
        self,
        interval: float,
        callback: Callable[[], None],
        *,
        name: str,
    ) -> object:
        self.intervals.append((interval, callback, name))
        return object()

    def run_worker(self, callback: Callable[[], None], **kwargs: object) -> None:
        self.workers.append((callback, kwargs))

    def call_from_thread(
        self,
        callback: Callable[..., None],
        *args: object,
    ) -> None:
        callback(*args)

    def query_one(self, *_args: object) -> _Indicator:
        return self.indicator

    def _submit_tracked_task(self, *args: Any, **kwargs: Any) -> object:
        self.submitted = (args, kwargs)
        return object()

    def _schedule_agents_async_refresh(self, *, source: str) -> None:
        self.refresh_sources.append(source)


class _Reporter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def phase(self, text: str) -> None:
        self.lines.append(text)

    def section(self, text: str) -> None:
        self.lines.append(text)

    def log(self, text: str, *, stream: str = "stdout") -> None:
        del stream
        self.lines.append(text)


def _snapshot(behind: int = 1) -> SyncStatusSnapshot:
    return SyncStatusSnapshot(
        10.0,
        (ProjectSyncStatus("alpha", "Alpha", "ready", behind=behind),),
    )


def _captured() -> CapturedIncomingHood:
    return CapturedIncomingHood(
        project_key="alpha",
        project="Alpha",
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="a" * 40,
        cache_id="alpha-cache",
        format_version=2,
        source_owner_kind="exact",
        source_username="alice",
        source_machine="zeus",
        top_hood="foo",
        hood_digest="b" * 64,
        run_count=2,
        family_count=1,
        cache_created_at=1.0,
    )


def test_startup_registers_one_timer_and_guarded_worker() -> None:
    app = _Harness()

    app._schedule_startup_agents_sync_check()
    app._schedule_startup_agents_sync_check()

    assert app.intervals == [
        (600.0, app._on_periodic_agents_sync_check, "agents-sync-check")
    ]
    assert len(app.workers) == 1
    assert app.workers[0][1] == {
        "name": "agents-sync-status-check",
        "thread": True,
        "exclusive": False,
        "group": "startup-loads",
    }
    assert app._agents_sync_check_in_flight is True


def test_timer_registration_uses_cached_config_without_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _Harness()
    app._agents_sync_check_interval_seconds = 90.0
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: pytest.fail("timer path must not load config"),
    )

    app._start_periodic_agents_sync_checks()
    app._start_periodic_agents_sync_checks()

    assert [(seconds, name) for seconds, _callback, name in app.intervals] == [
        (90.0, "agents-sync-check")
    ]


def test_periodic_tick_skips_overlap() -> None:
    app = _Harness()

    app._on_periodic_agents_sync_check()
    app._on_periodic_agents_sync_check()

    assert len(app.workers) == 1


def test_ordinary_tick_revalidates_without_network_and_applies_on_ui_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def get_status(**kwargs: object) -> SyncStatusSnapshot:
        calls.append(dict(kwargs))
        return _snapshot()

    monkeypatch.setattr(agents_sync, "get_agents_sync_status", get_status)
    monkeypatch.setattr(agents_sync.time, "monotonic", lambda: 101.0)
    app = _Harness()
    app._agents_sync_last_recompute_mono = 100.0

    app._on_periodic_agents_sync_check()
    app.workers[0][0]()

    assert calls == [
        {
            "refresh": False,
            "revalidate_only": True,
            "shutdown_requested": agents_sync.is_shutdown_requested,
        }
    ]
    assert app.indicator.snapshots == [_snapshot()]
    assert app._agents_sync_check_in_flight is False
    assert app._agents_sync_last_recompute_mono == 100.0


def test_long_cadence_recompute_uses_own_last_recompute_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def get_status(**kwargs: object) -> SyncStatusSnapshot:
        calls.append(dict(kwargs))
        # checked_at is intentionally fresh; cadence authority is app state.
        return SyncStatusSnapshot(10**9, ())

    monkeypatch.setattr(agents_sync, "get_agents_sync_status", get_status)
    monkeypatch.setattr(agents_sync.time, "monotonic", lambda: 2000.0)
    app = _Harness()
    app._agents_sync_last_recompute_mono = 100.0
    app._agents_sync_recompute_interval_seconds = 1800.0

    app._on_periodic_agents_sync_check()
    app.workers[0][0]()

    assert calls == [
        {
            "refresh": True,
            "revalidate_only": False,
            "shutdown_requested": agents_sync.is_shutdown_requested,
        }
    ]
    assert app._agents_sync_last_recompute_mono == 2000.0


def test_manual_sync_uses_tracked_deduplicated_scope_and_refreshes_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = (
        SyncOutcome("alpha", "Alpha", pulled=True),
        SyncOutcome("beta", "Beta", error="push failed"),
    )
    monkeypatch.setattr(agents_sync, "sync_agents", lambda: outcomes)
    app = _Harness()

    app.action_sync_agents()

    assert app.submitted is not None
    args, kwargs = app.submitted
    assert kwargs["dedup_key"] == "agents-sync"
    assert kwargs["exclusive_scopes"] == ("agents-sync",)
    assert kwargs["reload_on_complete"] is False
    reporter = _Reporter()
    task_result = args[3](reporter)
    assert task_result.success is False
    assert task_result.payload == outcomes
    assert task_result.message == "Agents repos: 1 current, 1 failed"
    assert "Alpha: current — pulled" in reporter.lines
    assert "Beta: failed — push failed" in reporter.lines

    kwargs["on_complete"](None)
    assert len(app.workers) == 1
    assert app._agents_sync_check_in_flight is True
    assert app.refresh_sources == ["agents_full_sync"]


def test_indicator_integration_captures_items_and_uses_no_network_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _captured()
    result = CachedIntegrationResult(
        captured,
        "applied",
        hoods_imported=1,
        runs_imported=2,
        families_imported=1,
    )
    calls: list[tuple[CapturedIncomingHood, ...]] = []

    def integrate(
        items: tuple[CapturedIncomingHood, ...],
    ) -> tuple[CachedIntegrationResult, ...]:
        calls.append(items)
        return (result,)

    monkeypatch.setattr(agents_sync, "integrate_cached_agent_updates", integrate)
    app = _Harness()
    app.indicator.pending_updates = (captured,)

    app.action_integrate_cached_agents()

    assert app.submitted is not None
    args, kwargs = app.submitted
    assert kwargs["dedup_key"] == "agents-sync"
    assert kwargs["exclusive_scopes"] == ("agents-sync",)
    reporter = _Reporter()
    task_result = args[3](reporter)
    assert calls == [(captured,)]
    assert task_result.success is True
    assert task_result.message == "Cached agents: 1 applied"
    assert (
        "Alpha: alice.zeus.foo — applied (1 hood, 2 runs, 1 family)" in reporter.lines
    )

    kwargs["on_complete"](None)
    assert len(app.workers) == 1
    assert app.refresh_sources == ["agents_cached_integration"]
