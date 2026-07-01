"""Tests for the ACE startup update toast."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.actions.update_toast import (
    UpdateToastMixin,
)
from sase.updates import OutdatedComponent, UpdateStatus

from tests.ace.tui.visual._ace_png_snapshot_helpers import patch_startup_loaders


def _status(count: int = 2) -> UpdateStatus:
    components = [
        OutdatedComponent(
            display_name="sase",
            role="host",
            installed_version="1.0.0",
            latest_version="1.1.0",
            distribution_name="sase",
        ),
        OutdatedComponent(
            display_name="github",
            role="plugin",
            installed_version="0.5.0",
            latest_version="0.6.0",
            distribution_name="sase-github",
        ),
        OutdatedComponent(
            display_name="telegram",
            role="plugin",
            installed_version="0.1.0",
            latest_version="0.2.0",
            distribution_name="sase-telegram",
        ),
        OutdatedComponent(
            display_name="nvim",
            role="plugin",
            installed_version="0.3.0",
            latest_version="0.4.0",
            distribution_name="sase-nvim",
        ),
    ]
    return UpdateStatus(checked_at=100.0, components=tuple(components[:count]))


def test_update_toast_message_recommends_update_keymap() -> None:
    message = update_toast._format_update_toast_message(_status())

    assert "2 updates" in message
    assert "sase" in message
    assert "1.0.0 → 1.1.0" in message
    assert "],U[/]" in message
    assert "update sase, core & plugins" in message


def test_update_toast_message_caps_component_list() -> None:
    message = update_toast._format_update_toast_message(_status(count=4))

    assert "…and 1 more" in message
    assert "nvim" not in message


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

        def set_available(self, count: int) -> None:
            self.count = count

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


def test_load_update_toast_config_defaults_to_ten_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(update_toast, "load_merged_config", dict)

    config = update_toast._load_update_toast_config()

    assert config.startup_toast is True
    assert config.indicator is True
    assert config.post_update_toast_diffstat is True
    assert config.check_ttl_seconds == 600.0


def test_load_update_toast_config_post_update_diffstat_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"post_update_toast_diffstat": False}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.post_update_toast_diffstat is False


def test_load_update_toast_config_indicator_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"indicator": False}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.indicator is False


def test_load_update_toast_config_minutes_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"check_ttl_minutes": 5}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.check_ttl_seconds == 300.0


def test_load_update_toast_config_legacy_hours_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"check_ttl_hours": 2}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.check_ttl_seconds == 7200.0


def test_load_update_toast_config_minutes_take_precedence_over_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"check_ttl_minutes": 10, "check_ttl_hours": 24}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.check_ttl_seconds == 600.0


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

    assert captured["ttl_seconds"] == 600.0


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

    async with AcePage(query='"toast"') as page:
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        notifications = list(page.app._notifications)
        assert len(notifications) == 1
        assert notifications[0].title == "↑ Updates available"
        assert "Press" in notifications[0].message

        page.app._show_startup_update_toast(status)
        await page.pause()
        assert len(list(page.app._notifications)) == 1
