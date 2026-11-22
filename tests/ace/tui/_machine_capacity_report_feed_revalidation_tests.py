"""Revalidation tests for the machine-capacity report feed."""

from __future__ import annotations

import time

import pytest

from sase.core.runner_slots import MachineCapacityReport
from tests.ace.tui._machine_capacity_report_feed_helpers import FeedApp, make_report


class _FakeClock:
    """Advance monotonic and wall time manually across 10s boundaries."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        mono: float = 1000.0,
        wall: float = 2000.0,
    ) -> None:
        self.mono = mono
        self.wall = wall
        monkeypatch.setattr(time, "monotonic", self._mono)
        monkeypatch.setattr(time, "time", self._wall)

    def _mono(self) -> float:
        return self.mono

    def _wall(self) -> float:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += seconds


def _stable_feed(
    report_source: object,
    *,
    token: str = "token",
    holds: list[dict[str, object]] | None = None,
    override: tuple[int, object | None] | None = None,
    liveness: dict[str, bool] | None = None,
) -> FeedApp:
    """Return a feed with stable injectable inputs and counters."""
    holds_value = [] if holds is None else holds
    override_value: tuple[int, object | None] = (
        (8, None) if override is None else override
    )
    liveness_value: dict[str, bool] = {} if liveness is None else liveness
    counters = {"token_probes": 0, "builds": 0}

    def token_probe() -> str:
        counters["token_probes"] += 1
        return token

    def hold_source(now_wall: float) -> list[dict[str, object]]:
        del now_wall
        return [dict(item) for item in holds_value]

    def override_source(now_wall: float) -> tuple[int, object | None]:
        del now_wall
        return override_value

    def liveness_source() -> dict[str, bool]:
        return dict(liveness_value)

    base_source = report_source

    def counting_source() -> MachineCapacityReport:
        counters["builds"] += 1
        assert callable(base_source)
        return base_source()  # type: ignore[operator]

    app = FeedApp(counting_source)
    app._machine_capacity_token_probe = token_probe  # type: ignore[assignment]
    app._machine_capacity_hold_source = hold_source  # type: ignore[attr-defined]
    app._machine_capacity_override_source = override_source  # type: ignore[attr-defined]
    app._machine_capacity_liveness_source = liveness_source  # type: ignore[attr-defined]
    app._feed_counters = counters  # type: ignore[attr-defined]
    return app


async def _run_tick(app: FeedApp) -> None:
    generation = int(app._machine_capacity_refresh_generation) + 1
    app._machine_capacity_refresh_generation = generation
    await app._run_machine_capacity_report_refresh(generation=generation)


def _installed_count(app: FeedApp) -> int:
    count = 0
    while not app._capacity_reports_installed.empty():
        app._capacity_reports_installed.get_nowait()
        count += 1
    return count


@pytest.mark.asyncio
async def test_unchanged_across_many_ten_second_boundaries_skips_rebuilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(monkeypatch)
    app = _stable_feed(lambda: make_report())
    await _run_tick(app)
    assert app._feed_counters["builds"] == 1  # type: ignore[attr-defined]
    assert _installed_count(app) == 1
    # Six further 10s boundaries with identical inputs: probes only.
    for _ in range(6):
        clock.advance(10.0)
        await _run_tick(app)
    assert app._feed_counters["token_probes"] == 7  # type: ignore[attr-defined]
    assert app._feed_counters["builds"] == 1  # type: ignore[attr-defined]
    assert _installed_count(app) == 0
    assert app._machine_capacity_report.occupied_capacity == 5.0


@pytest.mark.asyncio
async def test_token_change_rebuilds_but_skips_unchanged_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(monkeypatch)
    app = _stable_feed(lambda: make_report())
    await _run_tick(app)
    assert _installed_count(app) == 1
    clock.advance(10.0)
    app._machine_capacity_token_probe = lambda: "new-token"  # type: ignore[assignment]
    # Rebind stable inputs after swapping the token probe.
    app._machine_capacity_hold_source = lambda now_wall: []  # type: ignore[attr-defined]
    app._machine_capacity_override_source = lambda now_wall: (8, None)  # type: ignore[attr-defined]
    app._machine_capacity_liveness_source = lambda: {}  # type: ignore[attr-defined]
    await _run_tick(app)
    # Token change forces a rebuild, but the visible report is identical so
    # publication (metrics invalidation, row work, inspector) is skipped.
    assert app._feed_counters["builds"] == 2  # type: ignore[attr-defined]
    assert _installed_count(app) == 0


@pytest.mark.asyncio
async def test_token_probe_failure_fails_open_to_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(monkeypatch)
    app = _stable_feed(lambda: make_report())
    await _run_tick(app)
    assert _installed_count(app) == 1

    def failing_probe() -> str:
        raise OSError("stat unavailable")

    clock.advance(10.0)
    app._machine_capacity_token_probe = failing_probe  # type: ignore[assignment]
    await _run_tick(app)
    assert app._feed_counters["builds"] == 2  # type: ignore[attr-defined]
    # Same visible report: rebuild happened (fail open) but install skipped.
    assert _installed_count(app) == 0


class _ExpiringOverride:
    """Minimal override with expiry for revalidation tests."""

    def __init__(self, *, limit: int, expires_at: float) -> None:
        self.version = 1
        self.limit = limit
        self.created_at = expires_at - 100.0
        self.expires_at = expires_at
        self.source = "test"

    def is_active(self, now: float) -> bool:
        return now < self.expires_at


@pytest.mark.asyncio
async def test_override_expiry_without_token_change_rebuilds_and_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(monkeypatch)
    reports = {"occupied": 5.0, "limit": 4}

    def source() -> MachineCapacityReport:
        report = make_report(occupied=reports["occupied"])
        object.__setattr__(report, "effective_limit", float(reports["limit"]))
        return report

    override = _ExpiringOverride(limit=4, expires_at=clock.wall + 5.0)
    app = _stable_feed(source, override=(8, override))
    await _run_tick(app)
    assert _installed_count(app) == 1
    assert app._machine_capacity_report.effective_limit == 4.0
    # Cross expiry without touching the token: effective limit returns to 8
    # and the visible report changes, so the rebuild must install.
    clock.advance(10.0)
    reports["limit"] = 8
    await _run_tick(app)
    assert app._feed_counters["builds"] == 2  # type: ignore[attr-defined]
    assert _installed_count(app) == 1
    assert app._machine_capacity_report.effective_limit == 8.0


@pytest.mark.asyncio
async def test_hold_expiry_without_token_change_rebuilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(monkeypatch)
    live_holds = [{"armer": "test", "expires_at": clock.wall + 5.0}]
    reports = {"occupied": 5.0}

    def source() -> MachineCapacityReport:
        return make_report(occupied=reports["occupied"])

    def hold_source(now_wall: float) -> list[dict[str, object]]:
        return [
            dict(item) for item in live_holds if now_wall < float(item["expires_at"])
        ]

    app = _stable_feed(source)
    app._machine_capacity_hold_source = hold_source  # type: ignore[attr-defined]
    await _run_tick(app)
    assert _installed_count(app) == 1
    clock.advance(10.0)
    # Hold expired: same token, but holds differ, so a rebuild is due. The
    # visible report changes (fewer claims) and must install.
    reports["occupied"] = 4.0
    await _run_tick(app)
    assert app._feed_counters["builds"] == 2  # type: ignore[attr-defined]
    assert _installed_count(app) == 1
    assert app._machine_capacity_report.occupied_capacity == 4.0


@pytest.mark.asyncio
async def test_process_death_without_token_change_rebuilds_and_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(monkeypatch)
    alive: dict[str, bool] = {"/tmp/project/artifacts/worker": True}
    reports = {"occupied": 5.0}

    def source() -> MachineCapacityReport:
        return make_report(occupied=reports["occupied"])

    app = _stable_feed(source)
    app._machine_capacity_liveness_source = lambda: dict(alive)  # type: ignore[attr-defined]
    await _run_tick(app)
    assert _installed_count(app) == 1
    clock.advance(10.0)
    alive["/tmp/project/artifacts/worker"] = False
    reports["occupied"] = 4.0
    await _run_tick(app)
    assert app._feed_counters["builds"] == 2  # type: ignore[attr-defined]
    assert _installed_count(app) == 1
    assert app._machine_capacity_report.occupied_capacity == 4.0


@pytest.mark.asyncio
async def test_changed_inspector_fields_install_when_rebuilt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(monkeypatch)
    diagnostics: tuple[object, ...] = ()

    def source() -> MachineCapacityReport:
        report = make_report()
        object.__setattr__(report, "diagnostics", diagnostics)
        return report

    app = _stable_feed(source)
    await _run_tick(app)
    assert _installed_count(app) == 1
    clock.advance(10.0)
    # Token change forces the authoritative check; changed inspector-visible
    # diagnostics must then publish instead of being skipped as unchanged.
    diagnostics = ({"code": "stale-scan"},)
    app._machine_capacity_token_probe = lambda: "new-token"  # type: ignore[assignment]
    app._machine_capacity_hold_source = lambda now_wall: []  # type: ignore[attr-defined]
    app._machine_capacity_override_source = lambda now_wall: (8, None)  # type: ignore[attr-defined]
    app._machine_capacity_liveness_source = lambda: {}  # type: ignore[attr-defined]
    await _run_tick(app)
    assert app._feed_counters["builds"] == 2  # type: ignore[attr-defined]
    assert _installed_count(app) == 1


@pytest.mark.asyncio
async def test_inspector_open_forces_install_on_unchanged_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(monkeypatch)
    app = _stable_feed(lambda: make_report())
    await _run_tick(app)
    assert _installed_count(app) == 1

    class _Screen:
        def update_capacity_report(
            self, report: object, *, running_nodes: object = None
        ) -> None:
            del report, running_nodes

    app.screen = _Screen()  # type: ignore[attr-defined]
    clock.advance(10.0)
    # Token change forces a rebuild; the visible report is identical, but an
    # open inspector must still reinstall to keep running-nodes fresh.
    app._machine_capacity_token_probe = lambda: "new-token"  # type: ignore[assignment]
    app._machine_capacity_hold_source = lambda now_wall: []  # type: ignore[attr-defined]
    app._machine_capacity_override_source = lambda now_wall: (8, None)  # type: ignore[attr-defined]
    app._machine_capacity_liveness_source = lambda: {}  # type: ignore[attr-defined]
    await _run_tick(app)
    assert app._feed_counters["builds"] == 2  # type: ignore[attr-defined]
    assert _installed_count(app) == 1
