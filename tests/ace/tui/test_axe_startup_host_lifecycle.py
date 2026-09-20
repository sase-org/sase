"""ACE startup drives the service host, never the legacy AXE daemon."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.axe import AxeMixin


class _StartupHarness(AxeMixin):
    def __init__(self, *, running: bool, restart: bool, auto_start: bool) -> None:
        self.axe_running = running
        self._restart_axe = restart
        self._auto_start_axe = auto_start
        self.refreshes = 0

    async def _load_axe_status_async(self, **_kwargs: object) -> None:  # type: ignore[override]
        return

    def _schedule_axe_async_refresh(self) -> None:  # type: ignore[override]
        self.refreshes += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("running", "restart", "auto_start", "expected"),
    [
        (False, False, True, ["start"]),
        (True, True, True, ["restart"]),
        (True, False, True, []),
        (False, False, False, []),
        (False, True, True, ["start"]),
    ],
)
async def test_ace_startup_starts_or_restarts_the_service_host(
    monkeypatch: pytest.MonkeyPatch,
    running: bool,
    restart: bool,
    auto_start: bool,
    expected: list[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.service.control.start_service_host", lambda: calls.append("start")
    )
    monkeypatch.setattr(
        "sase.service.control.restart_service_host", lambda: calls.append("restart")
    )
    app = _StartupHarness(running=running, restart=restart, auto_start=auto_start)

    await app._run_axe_startup_init()

    assert calls == expected
    assert app.refreshes == len(expected)
