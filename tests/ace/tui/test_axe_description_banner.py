"""Unit coverage for the AXE description panel render modes."""

from __future__ import annotations

from rich.console import Console

from sase.ace.tui.widgets import AxeDescriptionBanner


def _rendered_lines(banner: AxeDescriptionBanner, *, width: int) -> list[str]:
    console = Console(width=width, color_system=None, force_terminal=False)
    with console.capture() as capture:
        console.print(banner.render(), end="")
    return [line.rstrip() for line in capture.get().splitlines()]


def test_collapsed_description_is_exactly_one_line() -> None:
    banner = AxeDescriptionBanner()
    banner.set_expanded(False)
    banner.show_lumberjack(
        "hooks",
        "Advance hook lifecycle state",
        "This body remains hidden while collapsed.",
    )

    assert _rendered_lines(banner, width=44) == [
        "▌ Advance hook lifecycle state           ▸ d"
    ]


def test_expanded_paragraph_reflows_author_hard_wraps() -> None:
    banner = AxeDescriptionBanner()
    banner.show_chop(
        "mentor_checks",
        "Check mentor reviews",
        "The author wrapped this line\nat a different source width.",
    )

    assert _rendered_lines(banner, width=32) == [
        "▌ Check mentor reviews       ▾ d",
        "▌",
        "▌ The author wrapped this line",
        "▌ at a different source width.",
    ]


def test_bullet_block_uses_hanging_indent() -> None:
    banner = AxeDescriptionBanner()
    banner.show_chop(
        "checks",
        "Run checks",
        "- A long first bullet wraps onto another line\n"
        "  and joins its source continuation\n"
        "* Second bullet",
    )

    assert _rendered_lines(banner, width=30) == [
        "▌ Run checks               ▾ d",
        "▌",
        "▌ • A long first bullet wraps",
        "▌   onto another line and",
        "▌   joins its source",
        "▌   continuation",
        "▌ • Second bullet",
    ]


def test_blank_gutter_row_separates_body_blocks() -> None:
    banner = AxeDescriptionBanner()
    banner.show_lumberjack(
        "hooks",
        "Advance hooks",
        "First paragraph.\n\nSecond paragraph.",
    )

    assert _rendered_lines(banner, width=30) == [
        "▌ Advance hooks            ▾ d",
        "▌",
        "▌ First paragraph.",
        "▌",
        "▌ Second paragraph.",
    ]


def test_disclosure_hint_requires_body_and_spare_width() -> None:
    with_body = AxeDescriptionBanner()
    with_body.set_expanded(False)
    with_body.show_chop("checks", "Run checks", "More detail.")
    assert _rendered_lines(with_body, width=24) == ["▌ Run checks         ▸ d"]
    assert _rendered_lines(with_body, width=12) == ["▌ Run checks"]

    without_body = AxeDescriptionBanner()
    without_body.set_expanded(False)
    without_body.show_chop("checks", "Run checks", "")
    assert _rendered_lines(without_body, width=24) == ["▌ Run checks"]


def test_overflow_row_reports_exact_dropped_row_count() -> None:
    banner = AxeDescriptionBanner()
    banner.set_max_lines(4)
    banner.show_chop(
        "checks",
        "Run checks",
        "\n\n".join(f"Paragraph {index}." for index in range(1, 5)),
    )

    assert _rendered_lines(banner, width=32) == [
        "▌ Run checks                 ▾ d",
        "▌",
        "▌ Paragraph 1.",
        "▌ … +6 more · e",
    ]


def test_empty_body_renders_identically_in_both_states() -> None:
    banner = AxeDescriptionBanner()
    banner.show_lumberjack("checks", "Poll slow checks", "")
    expanded = _rendered_lines(banner, width=32)

    banner.set_expanded(False)
    collapsed = _rendered_lines(banner, width=32)

    assert expanded == collapsed == ["▌ Poll slow checks"]


def test_generated_target_chip_survives_both_states() -> None:
    banner = AxeDescriptionBanner()
    banner.show_chop(
        "refresh_docs[sase]",
        "Refresh generated documentation",
        "Regenerate checked-in reference files.",
        generated=True,
        target_key="sase",
    )
    assert "· sase" in _rendered_lines(banner, width=48)[0]

    banner.set_expanded(False)
    assert "· sase" in _rendered_lines(banner, width=48)[0]


def test_empty_summary_falls_back_without_hiding() -> None:
    banner = AxeDescriptionBanner()
    banner.show_lumberjack("_oneshot", "  ", "")

    assert banner.display is True
    assert _rendered_lines(banner, width=32) == ["▌ No description configured"]


def test_hide_removes_banner_from_layout() -> None:
    banner = AxeDescriptionBanner()
    banner.show_chop("checks", "Run checks", "")

    banner.hide()

    assert banner.display is False
