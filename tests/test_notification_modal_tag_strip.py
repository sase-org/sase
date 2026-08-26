"""Tests for the NotificationTagStrip widget and the modal's strip wiring.

Covers strip rendering, click ranges, narrow-width reflow, and the visibility
predicate the modal applies when it refreshes the strip.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from rich.cells import cell_len

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_tags import (
    NotificationTagStrip,
    NotificationTagTab,
)
from sase.ace.tui.widgets import notification_tab_style

from tests._notification_modal_helpers import _FakeOptionList, _make_notification


@pytest.fixture(autouse=True)
def _shipped_notification_tab_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Beads' shipped lowered priority stable under broad xdist runs."""
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()
    monkeypatch.setattr(
        notification_tab_style,
        "load_merged_config",
        lambda: {"ace": {"notification_tabs": {"beads": {"priority": 0}}}},
    )


def _four_icon_tabs() -> list[NotificationTagTab]:
    """Return the four tabs the 120x40 Beads-panel fixture renders."""
    return [
        NotificationTagTab(tag="hitl", label="Gates", count=1, kind="hitl"),
        NotificationTagTab(tag="beads", label="Beads", count=3, kind="panel"),
        NotificationTagTab(tag="errors", label="Errors", count=1, kind="errors"),
        NotificationTagTab(tag="done", label="Done", count=1, kind="tag"),
    ]


def _wire_full_rebuild(modal: NotificationModal) -> tuple[_FakeOptionList, MagicMock]:
    """Stub every widget `_rebuild_list()` touches for a plain, attachment-free row."""
    option_list = _FakeOptionList([])
    strip = MagicMock()
    widgets: dict[str, Any] = {
        "#notification-list": option_list,
        "#notification-tag-tabs": strip,
        "#notification-file-title": MagicMock(),
        "#notification-file-content": MagicMock(),
    }

    def query_one(selector: str, *_args: Any, **_kwargs: Any) -> Any:
        try:
            return widgets[selector]
        except KeyError:
            raise LookupError(selector) from None

    modal.query_one = MagicMock(side_effect=query_one)  # type: ignore[method-assign]
    return option_list, strip


def test_tag_strip_click_posts_selected_tag() -> None:
    """The tag strip keeps stable click ranges for tag tabs."""
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    modal = NotificationModal([done, review])
    strip = NotificationTagStrip(modal._tag_tabs(), None)
    strip.post_message = MagicMock()  # type: ignore[method-assign]

    start, _end = strip._tab_ranges["done"]
    strip.on_click(SimpleNamespace(x=start))

    message = strip.post_message.call_args.args[0]
    assert isinstance(message, NotificationTagStrip.TabClicked)
    assert message.tag == "done"


def test_tag_strip_click_ranges_survive_a_two_cell_icon() -> None:
    """Ranges are terminal columns, so a wide icon must not shift later tabs.

    ``on_click`` compares ``event.x`` — a column — against these ranges, so
    measuring them in characters would put every tab right of a two-cell icon
    one column off and select the wrong one.
    """
    tabs = [
        NotificationTagTab(tag="deploys", label="Deploys", count=1, icon="🚀"),
        NotificationTagTab(tag="review", label="Review", count=2),
    ]
    strip = NotificationTagStrip(tabs, None)
    strip.post_message = MagicMock()  # type: ignore[method-assign]

    content = strip._build_content()
    assert content.plain.startswith(" 🚀 Deploys 1 ")
    start, end = strip._tab_ranges["review"]
    assert end == cell_len(content.plain)

    strip.on_click(SimpleNamespace(x=start))
    assert strip.post_message.call_args.args[0].tag == "review"


def test_tag_strip_keeps_full_labels_while_they_fit() -> None:
    """A strip wide enough for every label is left alone."""
    strip = NotificationTagStrip(_four_icon_tabs(), "beads")
    strip._width = 80

    assert "Gates" in strip._build_content().plain


def test_a_narrow_tag_strip_sheds_inactive_labels_instead_of_whole_tabs() -> None:
    """Every tab stays on screen and clickable when the strip cannot fit.

    The strip clips at the modal's width, so a full-label render that overflows
    drops trailing tabs entirely — they render nowhere and ``on_click`` has no
    range for them. Shedding inactive labels keeps each tab identified by the
    icon its resolution chain guarantees.
    """
    tabs = _four_icon_tabs()
    strip = NotificationTagStrip(tabs, "beads")
    assert cell_len(strip._build_content().plain) > 43

    strip._width = 43
    content = strip._build_content()

    assert cell_len(content.plain) <= 43
    # The active tab keeps its name so the strip still says where you are.
    assert " Beads 3▾" in content.plain
    assert "Gates" not in content.plain
    assert set(strip._tab_ranges) == {tab.tag for tab in tabs}
    assert strip._tab_ranges["done"][1] <= 43


def test_a_narrow_tag_strip_still_routes_a_click_to_the_last_tab() -> None:
    """The tab the full-label render used to clip is clickable again."""
    strip = NotificationTagStrip(_four_icon_tabs(), "beads")
    strip.post_message = MagicMock()  # type: ignore[method-assign]
    strip._width = 43
    strip._build_content()

    start, _end = strip._tab_ranges["done"]
    strip.on_click(SimpleNamespace(x=start))

    assert strip.post_message.call_args.args[0].tag == "done"


def test_tag_strip_rerenders_only_when_its_width_changes() -> None:
    """Resize reflows the strip, and a same-width resize does no work."""
    strip = NotificationTagStrip(_four_icon_tabs(), "beads")
    strip.update = MagicMock()  # type: ignore[method-assign]

    strip.on_resize(SimpleNamespace(size=SimpleNamespace(width=43)))
    assert strip._width == 43
    assert "Gates" not in strip.update.call_args.args[0].plain

    strip.update.reset_mock()
    strip.on_resize(SimpleNamespace(size=SimpleNamespace(width=43)))
    strip.update.assert_not_called()


def test_refresh_tag_strip_keeps_a_single_tab_visible() -> None:
    """A lone tab must not hide the strip; only zero tabs should."""
    only = _make_notification("only", action="JumpToAgent")
    modal = NotificationModal([only])
    strip = MagicMock()
    modal.query_one = MagicMock(return_value=strip)  # type: ignore[method-assign]

    modal._refresh_tag_strip()

    strip.remove_class.assert_called_once_with("hidden")
    strip.add_class.assert_not_called()


def test_refresh_tag_strip_hides_when_there_are_zero_tabs() -> None:
    """No notifications means no tabs, so the strip is the one case that hides."""
    modal = NotificationModal([])
    strip = MagicMock()
    modal.query_one = MagicMock(return_value=strip)  # type: ignore[method-assign]

    modal._refresh_tag_strip()

    strip.add_class.assert_called_once_with("hidden")
    strip.remove_class.assert_not_called()


def test_refresh_tag_strip_keeps_two_tabs_visible() -> None:
    """The already-working multi-tab case is unaffected by the predicate flip."""
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    modal = NotificationModal([done, review])
    strip = MagicMock()
    modal.query_one = MagicMock(return_value=strip)  # type: ignore[method-assign]

    modal._refresh_tag_strip()

    strip.remove_class.assert_called_once_with("hidden")
    strip.add_class.assert_not_called()


def test_dismiss_that_collapses_two_tabs_to_one_leaves_the_strip_visible() -> None:
    """Regression test: dismissing the last row of one tag must not hide the strip.

    Drives the real dismiss action and `_rebuild_list()` wiring rather than calling
    `_refresh_tag_strip()` directly, so it covers the call site and not just the
    predicate.
    """
    done = _make_notification("done", action="JumpToAgent")
    done.tags = ["done"]
    review = _make_notification("review", action="JumpToAgent")
    review.tags = ["review"]
    modal = NotificationModal([done, review])
    modal._active_notification_tag = "done"
    modal._get_selected_index = lambda: 0  # type: ignore[method-assign]
    _option_list, strip = _wire_full_rebuild(modal)

    with patch("sase.ace.tui.modals.notification_modal.mark_dismissed"):
        modal.action_dismiss_notification()

    assert modal._active_notification_tag == "review"
    strip.remove_class.assert_called_with("hidden")
    strip.add_class.assert_not_called()


def test_tag_strip_renders_a_down_mark_only_on_a_lowered_tab() -> None:
    """The shipped beads priority is the flagship deviation; others stay bare."""
    content = NotificationTagStrip(_four_icon_tabs(), "beads")._build_content().plain

    assert "Beads 3▾" in content
    assert "Gates 1 " in content
    assert "Errors 1 " in content
    assert "Done 1 " in content
    assert "▴" not in content
    assert content.count("▾") == 1


def test_tag_strip_click_ranges_survive_a_priority_mark() -> None:
    """A mark is one cell inside the tab range, so later clicks still land."""
    tabs = [
        NotificationTagTab(tag="beads", label="Beads", count=3, kind="panel"),
        NotificationTagTab(tag="review", label="Review", count=2, kind="tag"),
    ]
    strip = NotificationTagStrip(tabs, None)
    strip.post_message = MagicMock()  # type: ignore[method-assign]

    content = strip._build_content()
    assert "Beads 3▾" in content.plain
    start, end = strip._tab_ranges["review"]
    assert end == cell_len(content.plain)

    strip.on_click(SimpleNamespace(x=start))
    assert strip.post_message.call_args.args[0].tag == "review"

    strip.on_click(SimpleNamespace(x=end - 1))
    assert strip.post_message.call_args.args[0].tag == "review"


def test_a_narrow_tag_strip_keeps_the_priority_mark_after_shedding_labels() -> None:
    """A pushed-down tab is the one whose position most needs explaining."""
    strip = NotificationTagStrip(_four_icon_tabs(), "hitl")
    strip._width = 43
    content = strip._build_content().plain

    assert "Beads" not in content
    assert "▾" in content
    assert " 3▾" in content
