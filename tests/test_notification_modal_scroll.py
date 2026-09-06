"""Tests for NotificationModal detail-pane scroll key dispatch."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from textual import events
from textual.containers import VerticalScroll
from textual.widgets import OptionList

from sase.ace.testing.wait import wait_for
from sase.ace.tui.modals.notification_modal import NotificationModal

from tests._notification_modal_helpers import _TestApp, _make_notification

_ROOT = Path(__file__).resolve().parents[1]


class _StyledTestApp(_TestApp):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"


@pytest.mark.parametrize(
    ("key", "character"),
    [
        ("G", "G"),
        ("shift+g", None),
        ("shift+g", "G"),
        ("g", "G"),
    ],
)
@pytest.mark.parametrize(
    "focus_selector", ["#notification-list", "#notification-file-scroll"]
)
async def test_uppercase_g_reaches_detail_bottom_from_real_input_path(
    tmp_path: Path,
    key: str,
    character: str | None,
    focus_selector: str,
) -> None:
    path = tmp_path / "long.txt"
    path.write_text("\n".join(f"line {i:03d}" for i in range(240)), encoding="utf-8")
    notification = _make_notification("n1")
    notification.files = [str(path)]
    dismissed: list[object | None] = []

    async with _StyledTestApp().run_test(size=(120, 40)) as pilot:
        modal = NotificationModal([notification])
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()
        await pilot.pause()

        scroll = modal.query_one("#notification-file-scroll", VerticalScroll)
        await wait_for(pilot, lambda: scroll.max_scroll_y > 0)

        modal.query_one(focus_selector).focus()
        scroll.scroll_to(y=min(100, scroll.max_scroll_y - 1), animate=False)
        await pilot.pause()
        assert 0 < scroll.scroll_y < scroll.max_scroll_y

        bottom = MagicMock(wraps=modal.action_scroll_file_bottom)
        top = MagicMock(wraps=modal.action_scroll_file_top)
        modal.action_scroll_file_bottom = bottom  # type: ignore[method-assign]
        modal.action_scroll_file_top = top  # type: ignore[method-assign]

        pilot.app.post_message(events.Key(key, character))
        await pilot.pause()

        assert scroll.scroll_y == scroll.max_scroll_y
        assert modal._get_selected_index() == 0
        assert pilot.app.screen is modal
        assert dismissed == []
        bottom.assert_called_once_with()
        top.assert_not_called()


async def test_lowercase_g_reaches_detail_top_from_real_input_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "long.txt"
    path.write_text("\n".join(f"line {i:03d}" for i in range(240)), encoding="utf-8")
    notification = _make_notification("n1")
    notification.files = [str(path)]

    async with _StyledTestApp().run_test(size=(120, 40)) as pilot:
        modal = NotificationModal([notification])
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        scroll = modal.query_one("#notification-file-scroll", VerticalScroll)
        await wait_for(pilot, lambda: scroll.max_scroll_y > 0)

        scroll.scroll_to(y=min(100, scroll.max_scroll_y), animate=False)
        await pilot.pause()
        assert scroll.scroll_y > 0

        pilot.app.post_message(events.Key("g", "g"))
        await pilot.pause()

        assert scroll.scroll_y == 0
        assert modal._get_selected_index() == 0
        assert pilot.app.screen is modal


async def test_uppercase_g_is_harmless_with_empty_detail_pane() -> None:
    notification = _make_notification("n1")
    dismissed: list[object | None] = []

    async with _StyledTestApp().run_test(size=(120, 40)) as pilot:
        modal = NotificationModal([notification])
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()
        await pilot.pause()

        scroll = modal.query_one("#notification-file-scroll", VerticalScroll)
        assert scroll.max_scroll_y == 0

        pilot.app.post_message(events.Key("g", "G"))
        await pilot.pause()

        assert scroll.scroll_y == 0
        assert pilot.app.screen is modal
        assert dismissed == []
        assert modal._get_selected_index() == 0
