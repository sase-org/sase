"""Keep full AXE snapshots behind the first Services visit."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.actions.axe_display._refresh_full import AxeRefreshFullMixin


class _AxeScheduleHarness(AxeRefreshFullMixin):
    def __init__(self, *, current_tab: str = "agents", visited: bool = False) -> None:
        self.current_tab = current_tab
        self._axe_services_visited = visited
        self._axe_first_load_done = False
        self._axe_full_snapshot_ready = False
        self._axe_status_refresh_running = False
        self._axe_status_refresh_scheduled = False
        self._axe_status_refresh_pending = False
        self._axe_status_refresh_want_full = False
        self._axe_status_refresh_want_all_tails = False
        self.spawn_calls = 0
        self.load_kwargs: list[dict[str, object]] = []

    def _spawn_axe_status_refresh_task(self) -> None:
        self.spawn_calls += 1

    async def _load_axe_status_async(self, **kwargs: object) -> None:
        self.load_kwargs.append(dict(kwargs))


def test_hidden_services_sanity_stays_header_only() -> None:
    app = _AxeScheduleHarness(current_tab="agents", visited=False)
    assert app._axe_should_collect_full() is False
    assert app._axe_should_collect_full(sanity_due=True) is False
    app._schedule_axe_async_refresh()
    assert app._axe_status_refresh_want_full is False
    assert app._axe_status_refresh_want_all_tails is False
    assert app.spawn_calls == 1


def test_post_visit_sanity_and_visible_services_request_full() -> None:
    app = _AxeScheduleHarness(current_tab="agents", visited=True)
    assert app._axe_should_collect_full() is False
    assert app._axe_should_collect_full(sanity_due=True) is True
    app.current_tab = "services"
    assert app._axe_should_collect_full() is True
    app._schedule_axe_async_refresh()
    assert app._axe_status_refresh_want_full is True


def test_first_visit_during_inflight_header_keeps_full_pending() -> None:
    app = _AxeScheduleHarness(current_tab="agents", visited=False)
    app._axe_status_refresh_running = True
    app._schedule_axe_async_refresh()
    assert app._axe_status_refresh_want_full is False
    assert app._axe_status_refresh_pending is True
    assert app.spawn_calls == 0

    app.current_tab = "services"
    app._axe_services_visited = True
    app._schedule_axe_async_refresh()
    assert app._axe_status_refresh_want_full is True
    assert app._axe_status_refresh_pending is True
    assert app.spawn_calls == 0


def test_rapid_tab_switches_coalesce_one_full_request() -> None:
    app = _AxeScheduleHarness(current_tab="agents", visited=False)
    app._schedule_axe_async_refresh()
    assert app.spawn_calls == 1
    assert app._axe_status_refresh_scheduled is True

    app.current_tab = "services"
    app._axe_services_visited = True
    app._schedule_axe_async_refresh()
    app.current_tab = "agents"
    app._schedule_axe_async_refresh()
    app.current_tab = "services"
    app._schedule_axe_async_refresh()

    assert app.spawn_calls == 1
    assert app._axe_status_refresh_want_full is True


def test_hidden_header_request_does_not_escalate_itself() -> None:
    app = _AxeScheduleHarness(current_tab="agents", visited=False)
    app._schedule_axe_async_refresh()
    assert app._axe_status_refresh_want_full is False
    app._schedule_axe_async_refresh()
    assert app._axe_status_refresh_want_full is False
    assert app.spawn_calls == 1


@pytest.mark.asyncio
async def test_run_preserves_header_strength_when_want_full_is_unset() -> None:
    app = _AxeScheduleHarness(current_tab="services", visited=False)
    refreshed = await app._run_axe_status_refresh()
    assert refreshed is True
    assert app.load_kwargs == [
        {"include_full_snapshots": False, "tail_all_chop_logs": False}
    ]


@pytest.mark.asyncio
async def test_coalesced_full_request_is_not_dropped_by_header_run() -> None:
    app = _AxeScheduleHarness(current_tab="agents", visited=True)
    app._axe_status_refresh_want_full = True
    refreshed = await app._run_axe_status_refresh(include_full_snapshots=False)
    assert refreshed is True
    assert app.load_kwargs[0]["include_full_snapshots"] is True


@pytest.mark.asyncio
async def test_failed_load_still_schedules_pending_followup() -> None:
    app = _AxeScheduleHarness(current_tab="services", visited=True)
    app._axe_status_refresh_pending = True

    async def boom(**kwargs: object) -> None:
        app.load_kwargs.append(dict(kwargs))
        raise RuntimeError("collect failed")

    app._load_axe_status_async = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="collect failed"):
        await app._run_axe_status_refresh(include_full_snapshots=True)
    assert app._axe_status_refresh_running is False
    assert app.spawn_calls == 1
    assert app._axe_status_refresh_want_full is True


def test_spawn_failure_releases_scheduled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _AxeScheduleHarness(current_tab="services", visited=True)
    app._axe_status_refresh_scheduled = True

    def _fail_spawn(_owner: Any, coro: Any, **_kwargs: Any) -> None:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return None

    monkeypatch.setattr(
        "sase.ace.tui.actions.axe_display._refresh_full.spawn_pump_free_task",
        _fail_spawn,
    )
    AxeRefreshFullMixin._spawn_axe_status_refresh_task(app)
    assert app._axe_status_refresh_scheduled is False
