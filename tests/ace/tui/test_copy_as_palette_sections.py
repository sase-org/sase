"""Sectioned Copy as palette coverage: sections, gutter, badges, preview."""

from __future__ import annotations

import pytest
from textual.css.query import NoMatches
from textual.widgets import OptionList, Static

from sase.ace.tui.modals.copy_as_modal import CopyAsModal
from sase.ace.tui.modals.copy_as_types import (
    CopyAsContext,
    CopyAsRow,
    CopyAsSection,
)
from tests.ace.tui._copy_as_palette_helpers import CopyAsModalApp


def _section_row(
    key: str,
    section: str,
    label: str,
    *,
    target: str = "snippet",
    preview: str = "",
    value: str | None = None,
    marker: str | None = None,
    badge: str | None = None,
    disabled_reason: str | None = None,
) -> CopyAsRow:
    return CopyAsRow(
        key=key,
        key_display=key,
        target=target,
        label=label,
        section=section,
        marker=marker,
        badge=badge,
        value=value,
        preview=preview,
        disabled_reason=disabled_reason,
    )


def _sectioned_context(*rows: CopyAsRow, **kwargs) -> CopyAsContext:  # type: ignore[no-untyped-def]
    return CopyAsContext(
        group="question",
        subtitle="Q1/1 · Mac GUI",
        unknown_context="question",
        rows=rows,
        title="Copy from question",
        sections=(
            CopyAsSection(id="snippets", title="Snippets"),
            CopyAsSection(id="question", title="Question"),
        ),
        footer="1–2 copy · ⏎ highlighted · esc close",
        preview_pane=True,
        **kwargs,
    )


def _option_plains(modal: CopyAsModal) -> list[str]:
    option_list = modal.query_one("#copy-as-list", OptionList)
    return [
        str(option_list.get_option_at_index(index).prompt)
        for index in range(option_list.option_count)
    ]


async def test_section_grouping_and_order_skips_empty_sections() -> None:
    context = _sectioned_context(
        _section_row("t", "question", "Question text", preview="the question"),
        _section_row("1", "snippets", "First", preview="/tmp/a"),
        _section_row("2", "snippets", "Second", preview="/tmp/b"),
        _section_row("z", "unmatched", "Leftover", preview="/tmp/z"),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        plains = _option_plains(modal)

    assert plains[0] == "SNIPPETS"
    assert plains[1].startswith("1        First")
    assert plains[2].startswith("2        Second")
    assert plains[3] == "QUESTION"
    assert plains[4].startswith("t        Question text")
    # Rows whose section matches nothing still render instead of dropping.
    assert plains[5].startswith("z        Leftover")


async def test_marker_gutter_renders_between_key_and_label() -> None:
    context = _sectioned_context(
        _section_row("1", "snippets", "Done", marker="✓", preview="/tmp/a"),
        _section_row("2", "snippets", "Todo", preview="/tmp/b"),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        plains = _option_plains(modal)

    assert plains[1] == "1        ✓ Done  /tmp/a"
    assert plains[2] == "2          Todo  /tmp/b"


async def test_no_gutter_without_markers_or_request() -> None:
    context = _sectioned_context(
        _section_row("1", "snippets", "First", preview="/tmp/a"),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        plains = _option_plains(modal)

    assert not modal.context.wants_marker_gutter
    assert plains[1] == "1        First  /tmp/a"


async def test_gutter_request_renders_without_markers() -> None:
    context = _sectioned_context(
        _section_row("1", "snippets", "First", preview="/tmp/a"),
        show_marker_gutter=True,
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        plains = _option_plains(modal)

    assert modal.context.wants_marker_gutter
    assert plains[1] == "1          First  /tmp/a"


async def test_aligned_label_column() -> None:
    context = _sectioned_context(
        _section_row("1", "snippets", "A", preview="/tmp/a"),
        _section_row("2", "snippets", "Longer label", preview="/tmp/b"),
        label_width=12,
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        plains = _option_plains(modal)

    assert plains[1] == "1        A             /tmp/a"
    assert plains[2] == "2        Longer label  /tmp/b"
    assert plains[1].index("/tmp/a") == plains[2].index("/tmp/b")


async def test_badge_renders_dim_right_of_preview() -> None:
    context = _sectioned_context(
        _section_row(
            "3",
            "snippets",
            "Multi",
            preview="first line",
            badge="+2 lines",
        ),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        option_list = modal.query_one("#copy-as-list", OptionList)
        prompt = option_list.get_option_at_index(1).prompt

    assert prompt.plain == "3        Multi  first line +2 lines"
    badge_span = next(
        span
        for span in prompt.spans
        if prompt.plain[span.start : span.end] == "+2 lines"
    )
    assert "dim" in str(badge_span.style)


async def test_preview_shows_verbatim_value() -> None:
    value = "copy [/] and [bold]x exactly"
    context = _sectioned_context(
        _section_row("1", "snippets", "Tricky", value=value),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        preview = modal.query_one("#copy-as-preview", Static)

    assert preview.content.plain == value
    assert preview.content.spans == []
    assert preview.border_title == f"1 · Tricky · {len(value)} chars"


async def test_preview_multiline_overflow_caps_at_six_lines() -> None:
    value = "\n".join(f"line {index}" for index in range(8))
    context = _sectioned_context(
        _section_row("1", "snippets", "Multi", value=value),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        preview = modal.query_one("#copy-as-preview", Static)

    assert preview.content.plain == (
        "\n".join(f"line {index}" for index in range(6)) + "\n… +2 more lines"
    )
    assert preview.border_title == "1 · Multi · 8 lines"


async def test_preview_narrow_caps_at_three_lines() -> None:
    value = "\n".join(f"line {index}" for index in range(5))
    context = _sectioned_context(
        _section_row("1", "snippets", "Multi", value=value),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        assert modal.has_class("-narrow")
        preview = modal.query_one("#copy-as-preview", Static)

    assert preview.content.plain == "line 0\nline 1\nline 2\n… +2 more lines"


async def test_preview_disabled_row_shows_reason() -> None:
    context = _sectioned_context(
        _section_row("1", "snippets", "First", preview="/tmp/a"),
        _section_row(
            "o",
            "question",
            "Highlighted option",
            disabled_reason="No options to copy",
        ),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        option_list = modal.query_one("#copy-as-list", OptionList)
        option_list.highlighted = 3
        modal._update_preview()
        await pilot.pause()
        preview = modal.query_one("#copy-as-preview", Static)

    assert preview.content.plain == "No options to copy"
    assert preview.content.style == "$warning"


async def test_preview_updates_on_highlight_change() -> None:
    context = _sectioned_context(
        _section_row("1", "snippets", "First", value="/tmp/a"),
        _section_row("2", "snippets", "Second", value="/tmp/b"),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        preview = modal.query_one("#copy-as-preview", Static)
        assert preview.content.plain == "/tmp/a"

        await pilot.press("j")
        await pilot.pause()

    assert preview.content.plain == "/tmp/b"
    assert preview.border_title == "2 · Second · 6 chars"


async def test_initial_row_key_wins_over_first_enabled() -> None:
    context = _sectioned_context(
        _section_row("1", "snippets", "First", preview="/tmp/a"),
        _section_row("2", "snippets", "Second", preview="/tmp/b"),
        initial_row_key="2",
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("enter")
        await pilot.pause()

    assert app.results == [next(row for row in context.rows if row.key == "2")]


@pytest.mark.parametrize("initial", ["missing", None])
async def test_initial_row_key_falls_back_to_first_enabled(
    initial: str | None,
) -> None:
    context = _sectioned_context(
        _section_row("1", "snippets", "First", preview="/tmp/a"),
        _section_row("2", "snippets", "Second", preview="/tmp/b"),
        initial_row_key=initial,
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("enter")
        await pilot.pause()

    assert app.results == [next(row for row in context.rows if row.key == "1")]


async def test_initial_row_key_skips_disabled_row() -> None:
    context = _sectioned_context(
        _section_row(
            "1",
            "snippets",
            "First",
            preview="/tmp/a",
            disabled_reason="Unavailable",
        ),
        _section_row("2", "snippets", "Second", preview="/tmp/b"),
        initial_row_key="1",
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("enter")
        await pilot.pause()

    assert app.results == [next(row for row in context.rows if row.key == "2")]


async def test_custom_title_footer_and_unknown_key_message() -> None:
    context = _sectioned_context(
        _section_row("1", "snippets", "First", preview="/tmp/a"),
        unknown_key_message="Use 1, t, or q — nothing else copies",
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        assert modal.query_one("#copy-as-title", Static).content == "Copy from question"
        assert (
            modal.query_one("#copy-as-footer", Static).content
            == "1–2 copy · ⏎ highlighted · esc close"
        )
        await pilot.press("z")
        await pilot.pause()

    assert app.messages == [("Use 1, t, or q — nothing else copies", "warning")]


async def test_default_context_renders_legacy_chrome() -> None:
    context = CopyAsContext(
        group="patches",
        subtitle="SASE · copy_as_palette",
        unknown_context="Patches",
        rows=(
            CopyAsRow(
                key="n",
                key_display="n",
                target="name",
                label="Copy name",
                category="Identity",
                preview="visual_auth",
            ),
        ),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        assert modal.query_one("#copy-as-title", Static).content == "Copy as…"
        assert modal.query_one("#copy-as-footer", Static).content == (
            "enter select  ·  j/k or ↑/↓ navigate  ·  q/esc cancel"
        )
        with pytest.raises(NoMatches):
            modal.query_one("#copy-as-preview", Static)
        plains = _option_plains(modal)
        await pilot.press("z")
        await pilot.pause()

    assert plains == ["IDENTITY", "n        Copy name  visual_auth"]
    assert app.messages == [("Unknown copy key (Patches: n)", "warning")]
