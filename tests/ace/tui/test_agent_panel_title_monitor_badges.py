"""Monitor badge rendering in Agents-tab panel border titles."""

from __future__ import annotations

from sase.ace.tui.actions.agents._display_panel_titles import (
    _PANEL_SELECTED_CHROME_STYLE,
    AgentPanelCounts,
    agent_panel_border_title,
)
from sase.ace.tui.actions.agents._display_panels import (
    _PANEL_COUNT_STYLE,
    _PANEL_METRIC_STYLES,
)
from sase.gate_shell.state import GATE_FAILURE_GLYPH_COLOR, GATE_SETTLED_GLYPH_COLOR
from sase.monitor_state import MONITOR_GLYPH_COLOR, MONITOR_SETTLED_GLYPH_COLOR

from ._agent_panel_title_helpers import (
    _assert_title_range_style,
    _assert_title_span,
)


def test_settled_monitor_badge_follows_the_metric_chip() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2, settled_monitors=2),
    )

    assert title.plain == "@chop · 3 [R1 W2] ⚙2"


def test_settled_monitor_badge_follows_the_total_when_chip_is_empty() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(settled_monitors=2),
    )

    assert title.plain == "@chop · 3 ⚙2"


def test_zero_settled_monitors_renders_no_badge() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1),
    )

    assert title.plain == "@chop · 3 [R1]"


def test_no_counts_renders_no_settled_monitor_badge() -> None:
    title = agent_panel_border_title("chop", 3)

    assert title.plain == "@chop · 3"


def test_settled_monitor_badge_style_is_grey_and_separator_is_neutral() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, settled_monitors=2),
    )

    assert title.plain == "@chop · 3 [R1] ⚙2"
    badge_start = title.plain.index("⚙2")
    _assert_title_span(
        title,
        start=badge_start - 1,
        end=badge_start,
        style=_PANEL_COUNT_STYLE,
        text=" ",
    )
    _assert_title_span(
        title,
        start=badge_start,
        end=badge_start + 2,
        style=MONITOR_SETTLED_GLYPH_COLOR,
        text="⚙2",
    )


def test_selected_panel_keeps_settled_monitor_badge_grey() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, settled_monitors=2),
        selected=True,
    )

    assert title.plain == "❖ @chop · 3 [R1] ⚙2"
    r_position = title.plain.index("R1")
    _assert_title_range_style(
        title,
        start=r_position,
        end=r_position + 1,
        style=_PANEL_SELECTED_CHROME_STYLE,
    )
    _assert_title_range_style(
        title,
        start=r_position + 1,
        end=r_position + 2,
        style=_PANEL_METRIC_STYLES["running"],
    )
    badge_start = title.plain.index("⚙2")
    _assert_title_span(
        title,
        start=badge_start,
        end=badge_start + 2,
        style=MONITOR_SETTLED_GLYPH_COLOR,
        text="⚙2",
    )


def test_collapsed_panel_title_shows_settled_monitor_badge() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2, settled_monitors=2),
        collapsed=True,
    )

    assert title.plain == "▸ @chop · 3 [R1 W2] ⚙2"


def test_merged_panel_title_shows_settled_monitor_badge() -> None:
    title = agent_panel_border_title(
        None,
        3,
        merge_tribe_panels=True,
        counts=AgentPanelCounts(settled_monitors=2),
    )

    assert title.plain == "All agents · 3 ⚙2"


def test_running_monitor_badge_precedes_settled_badge_with_chip() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(
            running=1, waiting=2, running_monitors=1, settled_monitors=2
        ),
    )

    assert title.plain == "@chop · 3 [R1 W2] ⚙1 ⚙2"


def test_running_monitor_badge_with_chip_and_no_settled_monitors() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, running_monitors=1),
    )

    assert title.plain == "@chop · 3 [R1] ⚙1"


def test_running_monitor_badge_with_empty_chip() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running_monitors=1),
    )

    assert title.plain == "@chop · 3 ⚙1"


def test_zero_running_monitors_does_not_disturb_settled_badge() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, settled_monitors=2),
    )

    assert title.plain == "@chop · 3 [R1] ⚙2"


def test_running_and_settled_monitor_badge_styles() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(
            running=1, waiting=2, running_monitors=1, settled_monitors=2
        ),
    )

    assert title.plain == "@chop · 3 [R1 W2] ⚙1 ⚙2"
    running_badge_start = title.plain.index("⚙1")
    settled_badge_start = title.plain.index("⚙2")
    _assert_title_span(
        title,
        start=running_badge_start - 1,
        end=running_badge_start,
        style=_PANEL_COUNT_STYLE,
        text=" ",
    )
    _assert_title_span(
        title,
        start=running_badge_start,
        end=running_badge_start + 2,
        style=f"bold {MONITOR_GLYPH_COLOR}",
        text="⚙1",
    )
    _assert_title_span(
        title,
        start=settled_badge_start - 1,
        end=settled_badge_start,
        style=_PANEL_COUNT_STYLE,
        text=" ",
    )
    _assert_title_span(
        title,
        start=settled_badge_start,
        end=settled_badge_start + 2,
        style=MONITOR_SETTLED_GLYPH_COLOR,
        text="⚙2",
    )


def test_selected_panel_keeps_running_monitor_badge_amber() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, running_monitors=1, settled_monitors=2),
        selected=True,
    )

    assert title.plain == "❖ @chop · 3 [R1] ⚙1 ⚙2"
    running_badge_start = title.plain.index("⚙1")
    settled_badge_start = title.plain.index("⚙2")
    _assert_title_span(
        title,
        start=running_badge_start,
        end=running_badge_start + 2,
        style=f"bold {MONITOR_GLYPH_COLOR}",
        text="⚙1",
    )
    _assert_title_span(
        title,
        start=settled_badge_start,
        end=settled_badge_start + 2,
        style=MONITOR_SETTLED_GLYPH_COLOR,
        text="⚙2",
    )


def test_collapsed_panel_title_shows_both_monitor_badges() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(
            running=1,
            waiting=2,
            running_monitors=1,
            settled_monitors=2,
        ),
        collapsed=True,
    )

    assert title.plain == "▸ @chop · 3 [R1 W2] ⚙1 ⚙2"


def test_merged_panel_title_shows_both_monitor_badges() -> None:
    title = agent_panel_border_title(
        None,
        3,
        merge_tribe_panels=True,
        counts=AgentPanelCounts(running_monitors=1, settled_monitors=2),
    )

    assert title.plain == "All agents · 3 ⚙1 ⚙2"


def test_gate_badges_follow_monitor_badges_in_panel_title() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(
            running=1,
            running_monitors=1,
            settled_monitors=2,
            running_gates=3,
            settled_gates=4,
            failed_gates=5,
        ),
    )

    assert title.plain == "@chop · 3 [R1] ⚙1 ⚙2 ⋔3 ⋔4 ⋔5"


def test_gate_badge_styles_match_state_lanes() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running_gates=1, settled_gates=2, failed_gates=3),
    )

    assert title.plain == "@chop · 3 ⋔1 ⋔2 ⋔3"
    running_badge_start = title.plain.index("⋔1")
    settled_badge_start = title.plain.index("⋔2")
    failed_badge_start = title.plain.index("⋔3")
    _assert_title_span(
        title,
        start=running_badge_start,
        end=running_badge_start + 2,
        style="bold #0BCDEC",
        text="⋔1",
    )
    _assert_title_span(
        title,
        start=settled_badge_start,
        end=settled_badge_start + 2,
        style=GATE_SETTLED_GLYPH_COLOR,
        text="⋔2",
    )
    _assert_title_span(
        title,
        start=failed_badge_start,
        end=failed_badge_start + 2,
        style=f"bold {GATE_FAILURE_GLYPH_COLOR}",
        text="⋔3",
    )
