"""Tests for the ACE post-update restart toast."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.actions import post_update_toast, update_toast
from sase.ace.tui.actions.post_update_toast import PostUpdateToastMixin
from sase.ace.update_receipt import (
    UpdateToastReceipt,
    UpdateVersionTransition,
    write_pending_update_toast,
)
from sase.updates import OutdatedComponent, UpdateStatus
from tests.ace.tui.visual._ace_png_snapshot_helpers import patch_startup_loaders


def _receipt(*, created_at: float | None = None) -> UpdateToastReceipt:
    return UpdateToastReceipt(
        kind="managed",
        created_at=time.time() if created_at is None else created_at,
        primary=UpdateVersionTransition("sase", "0.5.0", "0.6.0"),
        plugins=(UpdateVersionTransition("sase-github", "1.2.0", "1.3.0"),),
        dependency_count=2,
    )


def _status() -> UpdateStatus:
    return UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="0.6.0",
                latest_version="0.7.0",
                distribution_name="sase",
            ),
        ),
    )


def test_post_update_toast_formats_update_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _App(PostUpdateToastMixin):
        def __init__(self) -> None:
            self._update_toast_shown = False
            self.calls: list[dict[str, Any]] = []

        def notify(self, message: str, **kwargs: Any) -> None:
            self.calls.append({"message": message, **kwargs})

    monkeypatch.setattr(
        post_update_toast,
        "read_and_clear_pending_update_toast",
        lambda: _receipt(),
    )
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(post_update_toast=True),
    )
    app = _App()

    app._maybe_show_post_update_toast()

    assert app._update_toast_shown is True
    assert len(app.calls) == 1
    call = app.calls[0]
    assert call["severity"] == "information"
    assert call["title"] == "✓ Updated to sase 0.6.0"
    assert "sase" in call["message"]
    assert "0.5.0" in call["message"]
    assert "0.6.0" in call["message"]
    assert "sase-github" in call["message"]
    assert "+2 dependencies" in call["message"]
    assert "Reloaded into the new version." in call["message"]


def test_post_update_toast_absent_receipt_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _App(PostUpdateToastMixin):
        def __init__(self) -> None:
            self._update_toast_shown = False
            self.calls = 0

        def notify(self, *_args: object, **_kwargs: object) -> None:
            self.calls += 1

    monkeypatch.setattr(
        post_update_toast,
        "read_and_clear_pending_update_toast",
        lambda: None,
    )
    app = _App()

    app._maybe_show_post_update_toast()

    assert app.calls == 0
    assert app._update_toast_shown is False


def test_post_update_toast_disabled_consumes_without_showing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    assert write_pending_update_toast(_receipt()) is True

    class _App(PostUpdateToastMixin):
        def __init__(self) -> None:
            self._update_toast_shown = False
            self.calls = 0

        def notify(self, *_args: object, **_kwargs: object) -> None:
            self.calls += 1

    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(post_update_toast=False),
    )
    app = _App()

    app._maybe_show_post_update_toast()

    assert app.calls == 0
    assert app._update_toast_shown is False
    assert not receipt_file.exists()


async def test_post_update_toast_appears_once_and_suppresses_available_toast(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    assert write_pending_update_toast(_receipt()) is True
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(
            startup_toast=True,
            post_update_toast=True,
        ),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: _status(),
    )

    async with AcePage(query='"toast"') as page:
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        await page.pause()
        notifications = list(page.app._notifications)
        assert len(notifications) == 1
        assert notifications[0].title == "✓ Updated to sase 0.6.0"
        assert "sase-github" in notifications[0].message
        assert not receipt_file.exists()
