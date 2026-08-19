"""Formatting for Agents-tab panel border titles."""

from __future__ import annotations

from sase.ace.tui.actions.agents._display_panel_titles import (
    _PANEL_FOLD_RESTORE_STYLE,
    _PANEL_ISOLATION_RESTORE_STYLE,
    _PANEL_SELECTED_CHROME_STYLE,
    AgentPanelCounts,
    agent_panel_border_title,
)
from sase.ace.tui.actions.agents._display_panels import (
    _PANEL_COUNT_STYLE,
    _PANEL_METRIC_STYLES,
)

from ._agent_panel_title_helpers import (
    _assert_title_range_style,
    _assert_title_span,
)


def test_collapsed_panel_title_prepends_chevron_and_preserves_summary() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2),
        collapsed=True,
    )

    assert title.plain == "▸ @chop · 3 [R1 W2]"


def test_panel_title_places_icon_before_tribe_label() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        collapsed=True,
        selected=True,
        icon="†",
    )

    assert title.plain == "▸ † @chop · 3"

    merged = agent_panel_border_title(
        None,
        3,
        merge_tribe_panels=True,
        icon="⌂",
    )
    assert merged.plain == "All agents · 3"


def test_panel_title_custom_color_is_scoped_to_tribe_identity() -> None:
    title = agent_panel_border_title(
        "research",
        12,
        counts=AgentPanelCounts(running=2),
        selected=True,
        icon="∴",
        color="#5FD7AF",
    )

    assert title.plain == "❖ ∴ @research · 12 [R2]"
    _assert_title_span(
        title,
        start=0,
        end=2,
        style=_PANEL_SELECTED_CHROME_STYLE,
        text="❖ ",
    )
    _assert_title_span(title, start=2, end=4, style="bold #5FD7AF", text="∴ ")
    _assert_title_span(title, start=4, end=13, style="bold #5FD7AF", text="@research")
    assert [
        (span.start, span.end) for span in title.spans if span.style == "bold #5FD7AF"
    ] == [(2, 4), (4, 13)]
    total_start = title.plain.index("12")
    _assert_title_span(
        title,
        start=total_start,
        end=total_start + 2,
        style=_PANEL_SELECTED_CHROME_STYLE,
        text="12",
    )


def test_panel_title_custom_color_preserves_hint_and_fold_chrome() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        collapsed=True,
        jump_hint="x",
        icon="†",
        color="#FFAF5F",
    )

    assert title.plain == "[x] ▸ † @chop · 3"
    _assert_title_span(title, start=0, end=4, style="bold #FFFF00", text="[x] ")
    _assert_title_span(title, start=4, end=6, style=_PANEL_COUNT_STYLE, text="▸ ")
    _assert_title_span(title, start=6, end=8, style="bold #FFAF5F", text="† ")
    _assert_title_span(title, start=8, end=13, style="bold #FFAF5F", text="@chop")
    _assert_title_span(title, start=13, end=16, style=_PANEL_COUNT_STYLE, text=" · ")


def test_panel_title_empty_color_keeps_legacy_tribe_style() -> None:
    title = agent_panel_border_title("chop", 3, icon="†", color="")

    assert title.plain == "† @chop · 3"
    _assert_title_span(title, start=0, end=2, style="bold #FFD75F", text="† ")
    _assert_title_span(title, start=2, end=7, style="bold #FFD75F", text="@chop")


def test_merged_panel_title_ignores_tribe_display_color() -> None:
    title = agent_panel_border_title(
        None,
        3,
        merge_tribe_panels=True,
        icon="⌂",
        color="#87D7FF",
    )

    assert title.plain == "All agents · 3"
    _assert_title_span(title, start=0, end=10, style="bold #AFFFFF", text="All agents")
    assert all(span.style != "bold #87D7FF" for span in title.spans)


def test_selected_expanded_panel_title_has_focus_marker() -> None:
    title = agent_panel_border_title(
        "chop",
        21,
        counts=AgentPanelCounts(
            asking=1,
            running=2,
            queued=7,
            waiting=3,
            failed=4,
            unread=5,
            read=6,
        ),
        selected=True,
    )

    assert title.plain == "❖ @chop · 21 [S1 R2 Q7 W3 F4 U5 D6]"
    selected_style = "#FFD75F"
    _assert_title_span(title, start=0, end=2, style=selected_style, text="❖ ")
    total_start = title.plain.index("21")
    _assert_title_span(
        title,
        start=total_start,
        end=total_start + 2,
        style=selected_style,
        text="21",
    )

    for character in "[]SRQWFUD":
        position = title.plain.index(character, total_start + 2)
        _assert_title_range_style(
            title,
            start=position,
            end=position + 1,
            style=selected_style,
        )

    for token, metric_name in (
        ("S1", "asking"),
        ("R2", "running"),
        ("Q7", "queued"),
        ("W3", "waiting"),
        ("F4", "failed"),
        ("U5", "unread"),
        ("D6", "read"),
    ):
        digit_position = title.plain.index(token, total_start + 2) + 1
        _assert_title_range_style(
            title,
            start=digit_position,
            end=digit_position + 1,
            style=_PANEL_METRIC_STYLES[metric_name],
        )

    separator_start = title.plain.index(" · ")
    _assert_title_span(
        title,
        start=separator_start,
        end=separator_start + 3,
        style=_PANEL_COUNT_STYLE,
        text=" · ",
    )


def test_selected_collapsed_panel_title_accents_chrome_without_marker() -> None:
    selected_style = _PANEL_SELECTED_CHROME_STYLE
    title = agent_panel_border_title(
        "research",
        225,
        counts=AgentPanelCounts(
            asking=10,
            running=21,
            waiting=32,
            failed=43,
            unread=54,
            read=65,
        ),
        collapsed=True,
        selected=True,
        icon="∴",
        color="#5FD7AF",
    )

    assert title.plain == "▸ ∴ @research · 225 [S10 R21 W32 F43 U54 D65]"
    assert title.plain.startswith("▸ ")
    assert "❖" not in title.plain
    _assert_title_span(title, start=0, end=2, style=selected_style, text="▸ ")
    _assert_title_span(title, start=2, end=4, style="bold #5FD7AF", text="∴ ")
    _assert_title_span(
        title,
        start=4,
        end=13,
        style="bold #5FD7AF",
        text="@research",
    )

    separator_start = title.plain.index(" · ")
    _assert_title_span(
        title,
        start=separator_start,
        end=separator_start + 3,
        style=_PANEL_COUNT_STYLE,
        text=" · ",
    )
    total_start = title.plain.index("225", separator_start)
    _assert_title_range_style(
        title,
        start=total_start,
        end=total_start + 3,
        style=selected_style,
    )

    chip_start = title.plain.index("[", total_start)
    for position in (
        index
        for index in range(chip_start, len(title.plain))
        if title.plain[index] in "[] SRWFUD"
    ):
        _assert_title_range_style(
            title,
            start=position,
            end=position + 1,
            style=selected_style,
        )

    for token, metric_name in (
        ("S10", "asking"),
        ("R21", "running"),
        ("W32", "waiting"),
        ("F43", "failed"),
        ("U54", "unread"),
        ("D65", "read"),
    ):
        token_start = title.plain.index(token, chip_start)
        _assert_title_range_style(
            title,
            start=token_start + 1,
            end=token_start + len(token),
            style=_PANEL_METRIC_STYLES[metric_name],
        )


def test_panel_title_places_isolation_restore_marker_after_tribe_name() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2),
        selected=True,
        isolation_restore_marked=True,
    )

    assert title.plain == "❖ @chop ↺ · 3 [R1 W2]"
    marker_start = title.plain.index("↺")
    _assert_title_span(
        title,
        start=marker_start,
        end=marker_start + 1,
        style=_PANEL_ISOLATION_RESTORE_STYLE,
        text="↺",
    )


def test_panel_title_places_fold_restore_marker_count_after_tribe_name() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2),
        fold_restore_marked_count=3,
    )

    assert title.plain == "@chop ▿3 · 3 [R1 W2]"
    marker_start = title.plain.index("▿3")
    _assert_title_span(
        title,
        start=marker_start,
        end=marker_start + 2,
        style=_PANEL_FOLD_RESTORE_STYLE,
        text="▿3",
    )
    assert _PANEL_FOLD_RESTORE_STYLE == _PANEL_ISOLATION_RESTORE_STYLE


def test_panel_title_composes_isolation_and_fold_restore_markers() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        isolation_restore_marked=True,
        fold_restore_marked_count=3,
    )

    assert title.plain == "@chop ↺ ▿3 · 3"
    isolation_start = title.plain.index("↺")
    fold_start = title.plain.index("▿3")
    _assert_title_span(
        title,
        start=isolation_start,
        end=isolation_start + 1,
        style=_PANEL_ISOLATION_RESTORE_STYLE,
        text="↺",
    )
    _assert_title_span(
        title,
        start=fold_start,
        end=fold_start + 2,
        style=_PANEL_FOLD_RESTORE_STYLE,
        text="▿3",
    )


def test_collapsed_panel_title_prepends_yellow_jump_hint() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2),
        collapsed=True,
        jump_hint="x",
    )

    assert title.plain == "[x] ▸ @chop · 3 [R1 W2]"
    _assert_title_span(
        title,
        start=0,
        end=4,
        style="bold #FFFF00",
        text="[x] ",
    )


def test_panel_title_renders_two_character_jump_hint() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2),
        collapsed=True,
        jump_hint="0Z",
    )

    assert title.plain == "[0Z] ▸ @chop · 3 [R1 W2]"
    _assert_title_span(
        title,
        start=0,
        end=5,
        style="bold #FFFF00",
        text="[0Z] ",
    )
