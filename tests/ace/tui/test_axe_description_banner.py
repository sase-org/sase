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


def test_service_proc_renders_teal_gutter_and_reflowed_body() -> None:
    banner = AxeDescriptionBanner()
    banner.show_service_proc(
        "scheduler",
        "Run automation",
        "- First bullet\n- Second bullet",
    )

    lines = _rendered_lines(banner, width=32)
    assert lines[0].startswith("▌ Run automation")
    assert lines[0].endswith("▾ d")
    assert "▌ • First bullet" in lines
    assert "▌ • Second bullet" in lines
    block = banner.render()
    assert block.theme.accent == "bold #00D7AF"


def test_service_collapsed_is_one_line_with_hint() -> None:
    banner = AxeDescriptionBanner()
    banner.set_expanded(False)
    banner.show_service_proc("scheduler", "Run automation", "Some body.")

    assert _rendered_lines(banner, width=44) == [
        "▌ Run automation                         ▸ d"
    ]


def test_service_overflow_has_no_edit_suffix() -> None:
    banner = AxeDescriptionBanner()
    banner.set_max_lines(4)
    banner.show_service_proc(
        "scheduler",
        "Run checks",
        "\n\n".join(f"Paragraph {index}." for index in range(1, 5)),
    )
    lines = _rendered_lines(banner, width=32)
    assert lines[-1] == "▌ … +6 more"
    assert "· e" not in lines[-1]


def test_chop_overflow_keeps_edit_suffix() -> None:
    banner = AxeDescriptionBanner()
    banner.set_max_lines(4)
    banner.show_chop(
        "checks",
        "Run checks",
        "\n\n".join(f"Paragraph {index}." for index in range(1, 5)),
    )
    assert _rendered_lines(banner, width=32)[-1] == "▌ … +6 more · e"


def test_set_keys_changes_hint_and_overflow_suffix() -> None:
    banner = AxeDescriptionBanner()
    banner.set_max_lines(4)
    banner.set_keys(toggle_key="D", edit_key="E")
    banner.show_chop(
        "checks",
        "Run checks",
        "\n\n".join(f"Paragraph {index}." for index in range(1, 5)),
    )
    lines = _rendered_lines(banner, width=32)
    assert lines[0].endswith("▾ D")
    assert lines[-1].endswith("· E")


def test_service_fallback_text_appears_for_blank_summary() -> None:
    banner = AxeDescriptionBanner()
    banner.show_service_proc("web", "  ", "")

    assert banner.display is True
    assert _rendered_lines(banner, width=32) == ["▌ No description configured"]


def test_identical_second_show_does_not_rerender() -> None:
    banner = AxeDescriptionBanner()
    banner.show_lumberjack("hooks", "Summary", "Body")
    calls = 0
    original = banner._rerender

    def _counting() -> None:
        nonlocal calls
        calls += 1
        original()

    banner._rerender = _counting  # type: ignore[method-assign]
    try:
        banner.show_lumberjack("hooks", "Summary", "Body")
        assert calls == 0
        banner.show_lumberjack("hooks", "Other", "Body")
        assert calls == 1
    finally:
        banner._rerender = original  # type: ignore[method-assign]
