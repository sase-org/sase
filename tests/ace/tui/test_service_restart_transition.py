"""Expected service-host restart transition: no false unhealthy toast."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from sase.ace.tui._service_health import derive_service_health
from sase.ace.tui.actions.axe_display._render_footer import AxeDisplayFooterMixin
from sase.ace.tui.actions.axe_display._service_restart_transition import (
    SERVICE_RESTART_POST_START_GRACE_SECONDS,
    ServiceRestartTransition,
    restart_transition_settled,
)


def _enablement(enabled: bool = True) -> Any:
    return SimpleNamespace(enabled=enabled, provenance="x", summary="enabled")


def _proc(
    name: str = "p",
    *,
    state: str = "running",
    desired: str = "running",
    enabled: bool = True,
    available: bool = True,
) -> Any:
    return SimpleNamespace(
        name=name,
        state=state,
        desired=desired,
        available=available,
        enablement=_enablement(enabled),
    )


def _snap(
    *procs: Any,
    host: str = "running",
    started_at: float | None = None,
    token: str = "t",
) -> Any:
    return SimpleNamespace(
        host=SimpleNamespace(state=host, started_at=started_at),
        procs=procs,
        change_token=token,
    )


class _FakeFooter:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, bool]] = []

    def set_service_health(self, health: Any, restarting: bool = False) -> None:
        self.calls.append((health, restarting))


class _Harness(AxeDisplayFooterMixin):
    def __init__(self, footer: _FakeFooter) -> None:
        self._service_status: Any = None
        self._service_restart_transition: ServiceRestartTransition | None = None
        self._service_health_notified: Any = None
        self.notifies: list[tuple[str, str]] = []
        self._footer = footer

    def notify(self, message: str, severity: str = "information") -> None:
        self.notifies.append((message, severity))

    def _update_axe_keybinding(self) -> None:
        self._push_service_health(self._footer)


def _begin(requested_at: float, now: float | None = None) -> ServiceRestartTransition:
    mono = time.monotonic() if now is None else now
    return ServiceRestartTransition(
        requested_at=requested_at,
        deadline=mono + SERVICE_RESTART_POST_START_GRACE_SECONDS,
    )


def test_shutdown_snapshots_do_not_toast_during_transition() -> None:
    footer = _FakeFooter()
    app = _Harness(footer)
    app._service_status = _snap(_proc("a"), _proc("b"), started_at=100.0)
    app._push_service_health(footer)
    assert app.notifies == []
    assert app._service_health_notified is not None

    requested_at = 200.0
    app._service_restart_transition = _begin(requested_at)

    # New Part B shape: host stopped.
    app._service_status = _snap(
        _proc("gateway", state="stopped"),
        host="stopped",
        started_at=100.0,
        token="shutdown",
    )
    app._push_service_health(footer)
    assert app.notifies == []
    assert footer.calls[-1][1] is True

    # Old shape: host running + all stopped (gateway first alphabetically).
    app._service_status = _snap(
        _proc("gateway", state="stopped"),
        _proc("scheduler", state="stopped"),
        host="running",
        started_at=100.0,
        token="shutdown-old",
    )
    app._push_service_health(footer)
    assert app.notifies == []
    assert footer.calls[-1][1] is True


def test_old_generation_healthy_does_not_settle() -> None:
    footer = _FakeFooter()
    app = _Harness(footer)
    app._service_status = _snap(_proc("a"), started_at=100.0)
    app._push_service_health(footer)
    requested_at = 200.0
    transition = _begin(requested_at)
    app._service_restart_transition = transition

    # Old-generation healthy snapshot during the stop window.
    app._service_status = _snap(_proc("a"), started_at=100.0, token="old-healthy")
    app._push_service_health(footer)
    assert app._service_restart_transition is transition
    assert app.notifies == []
    assert footer.calls[-1][1] is True

    # Later shutdown snapshot still does not toast.
    app._service_status = _snap(
        _proc("gateway", state="stopped"),
        host="stopped",
        started_at=100.0,
        token="shutdown",
    )
    app._push_service_health(footer)
    assert app.notifies == []
    assert footer.calls[-1][1] is True


def test_new_generation_healthy_settles_without_toast() -> None:
    footer = _FakeFooter()
    app = _Harness(footer)
    app._service_status = _snap(_proc("a"), started_at=100.0)
    app._push_service_health(footer)
    requested_at = 200.0
    app._service_restart_transition = _begin(requested_at)

    app._service_status = _snap(_proc("a"), started_at=200.0, token="new-healthy")
    app._push_service_health(footer)
    assert app._service_restart_transition is None
    assert app.notifies == []
    assert footer.calls[-1][1] is False


def test_restart_transition_settled_requires_new_generation() -> None:
    transition = ServiceRestartTransition(requested_at=200.0, deadline=9999.0)
    old = _snap(_proc("a"), started_at=100.0)
    assert not restart_transition_settled(transition, old, derive_service_health(old))
    new = _snap(_proc("a"), started_at=200.0)
    assert restart_transition_settled(transition, new, derive_service_health(new))
    bad = _snap(_proc("a", state="stopped"), host="stopped", started_at=300.0)
    assert not restart_transition_settled(transition, bad, derive_service_health(bad))


def test_expiry_clears_and_unhealthy_then_toasts_once(
    monkeypatch: Any,
) -> None:
    footer = _FakeFooter()
    app = _Harness(footer)
    app._service_status = _snap(_proc("a"), started_at=100.0)
    app._push_service_health(footer)
    requested_at = 200.0
    transition = ServiceRestartTransition(requested_at=requested_at, deadline=1.0)
    app._service_restart_transition = transition

    monkeypatch.setattr(time, "monotonic", lambda: 2.0)
    app._expire_service_restart_transition(transition)
    assert app._service_restart_transition is None

    app._service_status = _snap(
        _proc("gateway", state="stopped"),
        host="stopped",
        started_at=100.0,
        token="shutdown",
    )
    app._push_service_health(footer)
    assert len(app.notifies) == 1
    assert "Services unhealthy" in app.notifies[0][0]
    assert footer.calls[-1][1] is False

    # Same snapshot does not toast twice.
    app._push_service_health(footer)
    assert len(app.notifies) == 1


def test_stale_expiry_callback_does_nothing() -> None:
    footer = _FakeFooter()
    app = _Harness(footer)
    app._service_status = _snap(_proc("a"), started_at=100.0)
    app._push_service_health(footer)
    settled = _begin(200.0)
    app._service_restart_transition = None
    app._expire_service_restart_transition(settled)
    assert app._service_restart_transition is None
    assert app.notifies == []

    # Replaced transition: stale callback for the old one is ignored.
    first = _begin(200.0)
    second = _begin(300.0)
    app._service_restart_transition = second
    app._expire_service_restart_transition(first)
    assert app._service_restart_transition is second


def test_no_transition_keeps_existing_toast_behavior() -> None:
    footer = _FakeFooter()
    app = _Harness(footer)
    assert app._service_restart_transition is None
    app._service_status = _snap(_proc("a"), started_at=100.0)
    app._push_service_health(footer)
    assert app.notifies == []
    app._service_status = _snap(
        _proc("gateway", state="stopped"),
        host="stopped",
        started_at=100.0,
        token="shutdown",
    )
    app._push_service_health(footer)
    assert len(app.notifies) == 1
