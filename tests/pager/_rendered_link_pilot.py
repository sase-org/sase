"""Pilot helpers for rendered-link contract tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from textual.pilot import Pilot

from sase.ace.testing.wait import wait_for
from sase.pager.app import SasePager
from sase.pager.screen import PagerScreen
from sase.pager._labels import PagerLabel


def pager_screen(app: SasePager) -> PagerScreen:
    screen = app.screen
    assert isinstance(screen, PagerScreen)
    return screen


def label_for(screen: PagerScreen, display: str) -> PagerLabel:
    layer = screen._label_layer
    assert layer is not None
    matches = [label for label in layer.labels if label.target.text == display]
    assert matches, (
        f"no painted label for {display!r}; "
        f"have={[label.target.text for label in layer.labels]!r}"
    )
    assert len(matches) == 1, display
    return matches[0]


async def settle(pilot: Pilot[Any]) -> None:
    await pilot.pause(0.1)
    await pilot.pause(0.1)


async def press_hint(pilot: Pilot[Any], hint: str) -> None:
    for character in hint:
        await pilot.press(character)
    await settle(pilot)


async def wait_for_notification(
    pilot: Pilot[Any],
    notifications: list[tuple[str, str]],
    predicate: Callable[[str, str], bool],
    *,
    timeout: float = 5.0,
) -> None:
    await wait_for(
        pilot,
        lambda: any(
            predicate(message, severity) for message, severity in notifications
        ),
        timeout=timeout,
    )


async def follow_display(pilot: Pilot[Any], display: str) -> PagerScreen:
    app = pilot.app
    assert isinstance(app, SasePager)
    screen = pager_screen(app)
    await press_hint(pilot, label_for(screen, display).hint)
    return screen


def install_clipboard(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
    return copied


def install_editor(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    runs: list[list[str]] = []

    @contextmanager
    def fake_suspend(_app: object, **_metadata: object) -> Iterator[None]:
        yield

    monkeypatch.setattr("sase.pager.screen.suspend_for_external_tool", fake_suspend)
    monkeypatch.setattr(
        "sase.pager.screen.subprocess.run",
        lambda argv, **_kwargs: runs.append(list(argv)),
    )
    monkeypatch.setenv("EDITOR", "nvim")
    return runs


def install_media(
    monkeypatch: pytest.MonkeyPatch,
) -> list[list[object]]:
    views: list[list[object]] = []

    @contextmanager
    def fake_suspend(_app: object, **_metadata: object) -> Iterator[None]:
        yield

    class _Result:
        warning = None

    monkeypatch.setattr("sase.pager.screen.suspend_for_external_tool", fake_suspend)
    monkeypatch.setattr(
        "sase.pager.screen.view_artifact_files",
        lambda specs: views.append(list(specs)) or _Result(),
    )
    return views


def notify_capture(app: SasePager) -> list[tuple[str, str]]:
    notifications: list[tuple[str, str]] = []

    def notify(
        message: str, *, severity: str = "information", **_kwargs: object
    ) -> None:
        notifications.append((message, severity))

    app.notify = notify  # type: ignore[method-assign]
    return notifications
