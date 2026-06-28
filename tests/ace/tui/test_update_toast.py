"""Tests for the ACE startup update toast."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.actions.update_toast import (
    UpdateToastMixin,
)
from sase.ace.tui.modals.config_center_modal import center_tab_shortcut
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


def test_update_toast_message_uses_computed_updates_shortcut() -> None:
    shortcut = center_tab_shortcut("updates")
    assert shortcut is not None

    message = update_toast._format_update_toast_message(_status())

    assert "2 updates" in message
    assert "sase" in message
    assert "1.0.0 → 1.1.0" in message
    assert f"]{shortcut}[/]" in message


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
        lambda: update_toast._UpdateToastConfig(startup_toast=False),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: _status(),
    )
    app = _App()

    app._run_startup_update_toast_check()

    assert app.called is False


async def test_startup_update_toast_appears_once_in_tui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    status = _status()
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(startup_toast=True, check_ttl_hours=24),
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
