"""Tests for the NotificationTagStrip widget and the modal's strip wiring.

Covers strip rendering, click ranges, narrow-width reflow, and the visibility
predicate the modal applies when it refreshes the strip.
"""

from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import MagicMock, patch

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_constants import (
    NOTIFICATION_TAB_SHORTCUTS,
    notification_tab_shortcut,
)
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


def _n_tabs(count: int) -> list[NotificationTagTab]:
    """Return ``count`` uniquely tagged custom tabs in display order."""
    return [
        NotificationTagTab(tag=f"t{i:02d}", label=f"Tab{i:02d}", count=1, kind="tag")
        for i in range(count)
    ]


def _tier_width(
    tabs: list[NotificationTagTab],
    active: str | None,
    tier: Literal["full", "compact", "micro"],
) -> int:
    strip = NotificationTagStrip(tabs, active)
    return cell_len(strip._render_tabs(tier).plain)


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
    assert content.plain.startswith(" 1 🚀 Deploys 1 ")
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
    compact_width = _tier_width(tabs, "beads", "compact")
    assert cell_len(strip._build_content().plain) > compact_width

    strip._width = compact_width
    content = strip._build_content()

    assert strip._tier == "compact"
    assert cell_len(content.plain) <= compact_width
    # The active tab keeps its name so the strip still says where you are.
    assert " Beads 3▾" in content.plain
    assert "Gates" not in content.plain
    assert set(strip._tab_ranges) == {tab.tag for tab in tabs}
    assert strip._tab_ranges["done"][1] <= compact_width


def test_a_narrow_tag_strip_still_routes_a_click_to_the_last_tab() -> None:
    """The tab the full-label render used to clip is clickable again."""
    strip = NotificationTagStrip(_four_icon_tabs(), "beads")
    strip.post_message = MagicMock()  # type: ignore[method-assign]
    strip._width = _tier_width(_four_icon_tabs(), "beads", "compact")
    strip._build_content()

    start, _end = strip._tab_ranges["done"]
    strip.on_click(SimpleNamespace(x=start))

    assert strip.post_message.call_args.args[0].tag == "done"


def test_tag_strip_rerenders_only_when_its_width_changes() -> None:
    """Resize reflows the strip, and a same-width resize does no work."""
    strip = NotificationTagStrip(_four_icon_tabs(), "beads")
    strip.update = MagicMock()  # type: ignore[method-assign]

    compact_width = _tier_width(_four_icon_tabs(), "beads", "compact")
    strip.on_resize(SimpleNamespace(size=SimpleNamespace(width=compact_width)))
    assert strip._width == compact_width
    assert "Gates" not in strip.update.call_args.args[0].plain

    strip.update.reset_mock()
    strip.on_resize(SimpleNamespace(size=SimpleNamespace(width=compact_width)))
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
    strip._width = _tier_width(_four_icon_tabs(), "hitl", "compact")
    content = strip._build_content().plain

    assert "Beads" not in content
    assert "▾" in content
    assert " 3▾" in content


def _style_covering(text: Text, needle: str) -> str:
    start = text.plain.index(needle)
    for span in text.spans:
        if span.start <= start < span.end:
            return str(span.style)
    raise AssertionError(f"no span covering {needle!r} in {text.plain!r}")


def test_tag_strip_fit_ladder_picks_full_compact_and_micro() -> None:
    """The widest fitting tier is selected; shortcuts survive every rung."""
    tabs = _four_icon_tabs()
    full_width = _tier_width(tabs, "beads", "full")
    compact_width = _tier_width(tabs, "beads", "compact")
    micro_width = _tier_width(tabs, "beads", "micro")
    assert full_width > compact_width > micro_width

    strip = NotificationTagStrip(tabs, "beads")
    strip._width = full_width
    full = strip._build_content()
    assert strip._tier == "full"
    assert "Gates" in full.plain
    assert "Beads" in full.plain
    assert " │ " in full.plain

    strip._width = compact_width
    compact = strip._build_content()
    assert strip._tier == "compact"
    assert "Gates" not in compact.plain
    assert "Beads" in compact.plain
    assert all(digit in compact.plain for digit in "1234")

    strip._width = micro_width
    micro = strip._build_content()
    assert strip._tier == "micro"
    assert "Gates" not in micro.plain
    assert "Beads" not in micro.plain
    assert all(digit in micro.plain for digit in "1234")
    assert "│" in micro.plain
    assert set(strip._tab_ranges) == {tab.tag for tab in tabs}


def test_tag_strip_numbers_the_tenth_tab_zero_and_leaves_the_eleventh_unnumbered() -> (
    None
):
    """The tenth current tab is `0`; later tabs have no false number."""
    assert notification_tab_shortcut(9) == "0"
    assert notification_tab_shortcut(10) is None
    tabs = _n_tabs(11)
    strip = NotificationTagStrip(tabs, "t00")
    plain = strip._build_content().plain

    assert NOTIFICATION_TAB_SHORTCUTS == (
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "0",
    )
    for digit in NOTIFICATION_TAB_SHORTCUTS:
        assert f" {digit} " in plain
    assert "Tab10" in plain
    assert " 11 " not in plain
    assert set(strip._tab_ranges) == {tab.tag for tab in tabs}


def test_tag_strip_active_shortcut_uses_tab_accent_and_inactive_is_muted() -> None:
    """Active digit matches the tab accent; inactive digits stay muted."""
    strip = NotificationTagStrip(_four_icon_tabs(), "beads")
    content = strip._build_content()
    assert _style_covering(content, "2") == "#AF87FF"
    assert _style_covering(content, "4") == "#666666"


def test_tag_strip_click_range_includes_the_shortcut_digit() -> None:
    """The visible number is inside the tab's cell-accurate mouse range."""
    tabs = [
        NotificationTagTab(tag="deploys", label="Deploys", count=1, icon="🚀"),
        NotificationTagTab(tag="review", label="Review", count=2),
    ]
    strip = NotificationTagStrip(tabs, None)
    strip.post_message = MagicMock()  # type: ignore[method-assign]
    content = strip._build_content()
    start, end = strip._tab_ranges["deploys"]
    digit_column = start + 1  # full tier: leading space, then the digit
    assert 0 <= digit_column < end
    assert content.plain[start:end].lstrip().startswith("1")

    strip.on_click(SimpleNamespace(x=digit_column))
    assert strip.post_message.call_args.args[0].tag == "deploys"


def test_tag_strip_click_ranges_survive_wide_icon_and_priority_mark_with_digits() -> (
    None
):
    """Shortcut cells do not shift later ranges off a two-cell icon or mark."""
    tabs = [
        NotificationTagTab(tag="deploys", label="Deploys", count=1, icon="🚀"),
        NotificationTagTab(tag="beads", label="Beads", count=3, kind="panel"),
        NotificationTagTab(tag="review", label="Review", count=2, kind="tag"),
    ]
    strip = NotificationTagStrip(tabs, None)
    strip.post_message = MagicMock()  # type: ignore[method-assign]
    content = strip._build_content()
    start, end = strip._tab_ranges["review"]
    assert end == cell_len(content.plain)

    strip.on_click(SimpleNamespace(x=start))
    assert strip.post_message.call_args.args[0].tag == "review"
    strip.on_click(SimpleNamespace(x=end - 1))
    assert strip.post_message.call_args.args[0].tag == "review"
