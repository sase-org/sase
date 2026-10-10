"""Focused unit coverage for update-failure geometry."""

from __future__ import annotations

from sase.ace.tui.modals.update_failure_geometry import (
    CHROME_COLS,
    action_footer_lines,
    choose_outer_width,
    compute_geometry,
    content_cell_width,
    count_wrapped_rows,
    is_cramped,
    max_outer_size,
    pack_footer_lines,
)


def test_compact_failure_uses_preferred_width() -> None:
    geometry = compute_geometry(
        screen_w=240,
        screen_h=70,
        meta="sase update · apply · failed today at 10:00",
        headline="boom",
        body="line one\nline two",
        title="✗ Update failed",
    )

    assert geometry is not None
    assert geometry.width == 90
    assert geometry.needs_scroll is False
    assert geometry.show_scroll_hint is False
    assert geometry.height < 70


def test_long_command_widens_beyond_preferred() -> None:
    command = "git clone --depth 1 " + "x" * 160
    geometry = compute_geometry(
        screen_w=240,
        screen_h=70,
        meta="sase update · apply · failed today at 10:00",
        headline=command,
        body="\n".join(f"row {i}" for i in range(30)),
        title="✗ Update failed",
    )

    assert geometry is not None
    assert geometry.width > 90
    assert geometry.needs_scroll is False


def test_wide_transcript_reaches_maximum() -> None:
    body = "\n".join(f"output line {i:03d} " + "x" * 140 for i in range(500))
    geometry = compute_geometry(
        screen_w=160,
        screen_h=50,
        meta="sase update · apply · failed today at 10:00",
        headline="boom",
        body=body,
        title="✗ Update failed",
    )

    assert geometry is not None
    assert (geometry.width, geometry.height) == (156, 48)
    assert geometry.needs_scroll is True
    assert geometry.show_scroll_hint is True


def test_fitting_report_has_no_overflow() -> None:
    body = "\n".join(f"line {i}" for i in range(10))
    geometry = compute_geometry(
        screen_w=120,
        screen_h=40,
        meta="sase update · apply · failed today at 10:00",
        headline="boom",
        body=body,
        title="✗ Update failed",
    )

    assert geometry is not None
    assert geometry.needs_scroll is False
    assert geometry.show_scroll_hint is False


def test_small_terminal_stays_in_bounds() -> None:
    body = "\n".join(f"output line {i}" for i in range(200))
    for screen in ((80, 24), (60, 16)):
        geometry = compute_geometry(
            screen_w=screen[0],
            screen_h=screen[1],
            meta="sase update · apply · failed today at 10:00",
            headline="a very long error line " + "y" * 120,
            body=body,
            title="✗ Update failed",
        )

        assert geometry is not None
        max_w, max_h = max_outer_size(*screen)
        assert geometry.width <= max_w
        assert geometry.height <= max_h
        assert len(geometry.footer_lines) >= 1


def test_minimum_terminal_keeps_actions_and_one_row() -> None:
    geometry = compute_geometry(
        screen_w=40,
        screen_h=12,
        meta="sase update · apply · failed today at 10:00",
        headline="long metadata error " + "z" * 80,
        body="\n".join(f"line {i}" for i in range(50)),
        title="✗ Update failed",
    )

    assert geometry is not None
    assert geometry.width <= 40
    assert geometry.height <= 12
    assert geometry.cramped is True
    footer_text = " ".join(geometry.footer_lines)
    for key in ("u", "d", "y", "q"):
        assert key in footer_text


def test_zero_dimensions_defer_layout() -> None:
    assert (
        compute_geometry(
            screen_w=0,
            screen_h=40,
            meta="m",
            headline="h",
            body="b",
            title="t",
        )
        is None
    )
    assert (
        compute_geometry(
            screen_w=80,
            screen_h=0,
            meta="m",
            headline="h",
            body="b",
            title="t",
        )
        is None
    )


def test_unicode_tabs_and_literal_markup_agree() -> None:
    body = "héllo\tworld\n\n[bold]literal[/bold]\n" + "w" * 200 + "\n trailing\n"
    geometry = compute_geometry(
        screen_w=120,
        screen_h=40,
        meta="sase update · apply · failed today at 10:00",
        headline="error with \t tab and … wide 漢字",
        body=body,
        title="✗ Update failed",
    )

    assert geometry is not None
    inner = geometry.inner_width
    assert inner == geometry.width - CHROME_COLS
    # Blank lines, trailing newline, and the long token all count.
    assert count_wrapped_rows(body, inner) >= body.count("\n")
    assert content_cell_width("[bold]hi[/bold]") == len("[bold]hi[/bold]")


def test_empty_output_stays_compact() -> None:
    geometry = compute_geometry(
        screen_w=120,
        screen_h=40,
        meta="sase update · apply · failed today at 10:00",
        headline="boom",
        body="No output was captured.",
        title="✗ Update failed",
    )

    assert geometry is not None
    assert geometry.needs_scroll is False
    assert geometry.width == 90


def test_exact_fit_and_one_row_overflow_are_stable() -> None:
    kwargs: dict[str, object] = {
        "screen_w": 100,
        "screen_h": 30,
        "meta": "sase update · apply · failed today at 10:00",
        "headline": "boom",
        "title": "✗ Update failed",
    }
    first = compute_geometry(body="a\nb", **kwargs)  # type: ignore[arg-type]
    second = compute_geometry(body="a\nb", **kwargs)  # type: ignore[arg-type]
    assert first is not None and second is not None
    assert (first.width, first.height) == (second.width, second.height)
    assert first.show_scroll_hint == second.show_scroll_hint

    overflow = compute_geometry(
        body="a\nb\n" + "\n".join("x" for _ in range(100)), **kwargs
    )  # type: ignore[arg-type]
    assert overflow is not None
    repeated = compute_geometry(
        body="a\nb\n" + "\n".join("x" for _ in range(100)), **kwargs
    )  # type: ignore[arg-type]
    assert repeated is not None
    assert (overflow.width, overflow.height) == (repeated.width, repeated.height)


def test_footer_packs_between_groups() -> None:
    lines = pack_footer_lines(
        ("u open Update", "d dismiss", "y copy", "q/Esc close"), 200
    )
    assert lines == ("u open Update · d dismiss · y copy · q/Esc close",)
    narrow = action_footer_lines(30)
    assert len(narrow) >= 1
    assert "open Update" not in " ".join(narrow)


def test_cramped_uses_full_rectangle() -> None:
    assert is_cramped(59, 40) is True
    assert is_cramped(80, 15) is True
    assert is_cramped(80, 24) is False
    assert max_outer_size(40, 12) == (40, 12)
    assert max_outer_size(240, 70) == (236, 68)
    assert choose_outer_width(screen_w=40, screen_h=12, required_width=10) == 40
    assert choose_outer_width(screen_w=240, screen_h=70, required_width=10) == 90
