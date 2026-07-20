"""Tests for displaying the ACE startup update toast."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.actions.update_toast import UpdateToastMixin

from tests.ace.tui._update_toast_helpers import _status
from tests.ace.tui.visual._ace_png_snapshot_helpers import patch_startup_loaders


def test_show_startup_update_toast_is_once_per_session() -> None:
    class _App(UpdateToastMixin):
        def __init__(self) -> None:
            self._update_toast_shown = False
            self.calls: list[dict[str, Any]] = []

        def notify(self, message: str, **kwargs: Any) -> None:
            self.calls.append({"message": message, **kwargs})

    app = _App()

    app._show_startup_update_toast(_status())
    app._show_startup_update_toast(_status())

    assert len(app.calls) == 1
    assert app.calls[0]["severity"] == "information"
    assert app.calls[0]["title"] == "↑ Updates available"


def test_startup_update_check_respects_disabled_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _App(UpdateToastMixin):
        def __init__(self) -> None:
            self.called = False

        def call_from_thread(self, callback: object, *args: object) -> None:
            self.called = True

    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(
            startup_toast=False,
            indicator=False,
        ),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: _status(),
    )
    app = _App()

    app._run_startup_update_toast_check()

    assert app.called is False


def test_startup_update_check_updates_indicator_when_toast_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Indicator:
        def __init__(self) -> None:
            self.count = 0
            self.core = False

        def set_available(
            self,
            count: int,
            *,
            core: bool = False,
            agent_cli_count: int = 0,
            manual_agent_cli_count: int = 0,
        ) -> None:
            del manual_agent_cli_count
            self.count = count + agent_cli_count
            self.core = core

    class _App(UpdateToastMixin):
        def __init__(self) -> None:
            self.indicator = _Indicator()
            self.toast_calls = 0

        def call_from_thread(self, callback: Any, *args: object) -> None:
            callback(*args)

        def query_one(self, *_args: object) -> _Indicator:
            return self.indicator

        def notify(self, *_args: object, **_kwargs: object) -> None:
            self.toast_calls += 1

    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(
            startup_toast=False,
            indicator=True,
        ),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: _status(count=2),
    )
    app = _App()

    app._run_startup_update_toast_check()

    assert app.indicator.count == 2
    assert app.toast_calls == 0


def test_startup_update_check_passes_default_ttl_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(),
    )

    def _fake_get(**kwargs: object) -> None:
        captured.update(kwargs)
        return None

    monkeypatch.setattr(update_toast, "get_cached_update_status", _fake_get)

    class _App(UpdateToastMixin):
        def call_from_thread(self, callback: object, *args: object) -> None:
            raise AssertionError("no toast should be shown when status is None")

    _App()._run_startup_update_toast_check()

    assert captured == {"ttl_seconds": 600.0}


async def test_startup_update_toast_appears_once_in_tui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    status = _status()
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(startup_toast=True),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: status,
    )

    async with AcePage(query='"toast"', startup_policy="real") as page:
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        notifications = list(page.app._notifications)
        assert len(notifications) == 1
        assert notifications[0].title == "↑ Updates available"
        assert "Press" in notifications[0].message

        page.app._show_startup_update_toast(status)
        await page.pause()
        assert len(list(page.app._notifications)) == 1
