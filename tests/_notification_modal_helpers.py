"""Shared helpers for NotificationModal tests."""

from typing import Any
from unittest.mock import MagicMock

from textual.app import App, ComposeResult

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.notifications import Notification


def _make_notification(notification_id: str, action: str | None = None) -> Notification:
    """Create a minimal notification object for modal tests."""
    return Notification(
        id=notification_id,
        timestamp="2026-03-17T12:00:00-04:00",
        sender="test",
        action=action,
    )


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class _FakeOptionList:
    def __init__(self, options: list[Any]) -> None:
        self.options = list(options)
        self.highlighted: int | None = None

    @property
    def option_count(self) -> int:
        return len(self.options)

    def get_option_at_index(self, row: int) -> Any:
        return self.options[row]

    def clear_options(self) -> None:
        self.options.clear()

    def add_option(self, option: Any) -> None:
        self.options.append(option)

    def add_class(self, _class_name: str) -> None:
        return


class _KeyEvent:
    def __init__(self, key: str, character: str | None) -> None:
        self.key = key
        self.character = character
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


def _wire_fake_option_list(
    modal: NotificationModal, *, highlighted_index: int = 0
) -> _FakeOptionList:
    option_list = _FakeOptionList(modal._create_sectioned_options())
    row = modal._row_for_notification_index(  # type: ignore[arg-type]
        option_list, highlighted_index
    )
    option_list.highlighted = row

    def query_one(selector: str, *_args: Any, **_kwargs: Any) -> Any:
        if selector == "#notification-list":
            return option_list
        raise LookupError(selector)

    modal.query_one = MagicMock(side_effect=query_one)  # type: ignore[method-assign]
    return option_list
