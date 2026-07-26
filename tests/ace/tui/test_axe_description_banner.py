"""Unit coverage for the AXE description banner render modes."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets import AxeDescriptionBanner


def _rendered_text(banner: AxeDescriptionBanner) -> Text:
    rendered = banner.render()
    assert isinstance(rendered, Text)
    return rendered


def test_show_lumberjack_uses_gold_accent_and_description_style() -> None:
    banner = AxeDescriptionBanner()

    banner.show_lumberjack("hooks", "Advance hook lifecycle state")

    rendered = _rendered_text(banner)
    assert banner.display is True
    assert rendered.plain == "▌ Advance hook lifecycle state"
    assert rendered.spans[0].style == "bold #FFD700"
    assert rendered.spans[1].style == "italic #D7D7AF"
    assert rendered.overflow == "ellipsis"


def test_show_chop_uses_copper_accent() -> None:
    banner = AxeDescriptionBanner()

    banner.show_chop("mentor_checks", "Check completed mentor reviews")

    rendered = _rendered_text(banner)
    assert rendered.plain == "▌ Check completed mentor reviews"
    assert rendered.spans[0].style == "#D7AF87"
    assert rendered.spans[1].style == "italic #D7D7AF"


def test_show_generated_chop_appends_target_chip() -> None:
    banner = AxeDescriptionBanner()

    banner.show_chop(
        "refresh_docs[sase]",
        "Refresh generated documentation",
        generated=True,
        target_key="sase",
    )

    rendered = _rendered_text(banner)
    assert rendered.plain == "▌ Refresh generated documentation  · sase"
    assert rendered.spans[-1].style == "dim #B87333"


def test_empty_description_falls_back_without_hiding() -> None:
    banner = AxeDescriptionBanner()

    banner.show_lumberjack("_oneshot", "  ")

    rendered = _rendered_text(banner)
    assert banner.display is True
    assert rendered.plain == "▌ No description configured"
    assert rendered.spans[-1].style == "dim italic"


def test_hide_removes_banner_from_layout() -> None:
    banner = AxeDescriptionBanner()
    banner.show_chop("checks", "Run checks")

    banner.hide()

    assert banner.display is False
