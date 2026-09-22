"""Tests for Agents-tab info panel count rendering."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.agent_count_chip import AGENT_COUNT_CHIP_QUEUED_STYLE

from ._agent_info_panel_helpers import (
    AgentInfoPanel,
    collect_rich_text,
    collect_text,
    style_at_plain_index,
    style_for_plain_segment,
)


def test_sase_agent_headline_renders_before_concrete_metrics() -> None:
    panel = AgentInfoPanel()
    panel._position = 2
    panel._total = 12
    panel._unread_count = 3
    panel._asking_count = 2
    panel._running_count = 5
    panel._waiting_count = 2
    panel._failed_count = 1
    panel._read_count = 0
    panel._sase_agent_count = 12

    plain = collect_text(panel)

    assert plain.startswith(
        "12 [5 running · 2 stopped · 2 waiting · 1 failed · 3 unread]"
    )
    assert "Agents: 2/12" not in plain


def test_proc_shell_badge_renders_after_status_strip_with_light_blue_style() -> None:
    panel = AgentInfoPanel()
    panel._sase_agent_count = 21
    panel._proc_shell_count = 23
    panel._running_count = 6
    panel._waiting_count = 8
    panel._read_count = 7

    text = collect_rich_text(panel)
    header_prefix = text.plain.split(" · group:", 1)[0]

    assert header_prefix == ("21 agents [6 running · 8 waiting · 7 done] ⚙23")
    assert header_prefix.index("]") < header_prefix.index("⚙")
    assert header_prefix.index("⚙") < header_prefix.index("23")
    assert "procs" not in header_prefix
    assert "agents ·" not in header_prefix
    badge_start = text.plain.index("⚙23")
    assert style_at_plain_index(text, badge_start) == "bold #5FD7FF"
    assert style_at_plain_index(text, badge_start + 1) == "bold #5FD7FF"
    assert style_at_plain_index(text, badge_start + 2) == "bold #5FD7FF"


def test_proc_shell_badge_hidden_at_zero_keeps_agent_only_prefix() -> None:
    panel = AgentInfoPanel()
    panel._sase_agent_count = 5
    panel._proc_shell_count = 0

    plain = collect_text(panel)
    counts_prefix = plain.split(" · group:", 1)[0]

    assert counts_prefix == "5 [0 running]"
    assert "⚙" not in counts_prefix
    assert "agents" not in counts_prefix


def test_agent_count_strip_reports_starting_separately() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_agent_counts(
            unread=1,
            asking=2,
            running=3,
            waiting=4,
            failed=5,
            read=6,
            total=12,
            starting=7,
        )

    plain = collect_text(panel)

    assert plain.startswith(
        "12 [3 running · 2 stopped · 7 starting · "
        "4 waiting · 5 failed · 1 unread · 6 done]"
    )


def test_agent_count_numbers_have_rich_styles() -> None:
    panel = AgentInfoPanel()
    panel._sase_agent_count = 20
    panel._asking_count = 31
    panel._starting_count = 37
    panel._running_count = 42
    panel._waiting_count = 53
    panel._unread_count = 64
    panel._read_count = 75
    panel._failed_count = 86

    text = collect_rich_text(panel)

    count_styles = {
        "total": style_for_plain_segment(text, "20"),
        "asking": style_for_plain_segment(text, "31"),
        "starting": style_for_plain_segment(text, "37"),
        "running": style_for_plain_segment(text, "42"),
        "waiting": style_for_plain_segment(text, "53"),
        "failed": style_for_plain_segment(text, "86"),
        "unread": style_for_plain_segment(text, "64"),
        "read": style_for_plain_segment(text, "75"),
    }
    assert count_styles == {
        "total": "bold #FFFFFF",
        "asking": "bold #FFAF00",
        "starting": "bold #1a1a1a on #87D7FF",
        "running": "bold #00D7AF",
        "waiting": "bold #AF87FF",
        "failed": "bold #FF5F5F",
        "unread": "bold #1a1a1a on #FFD700",
        "read": "bold #5FD7FF",
    }

    label_styles = {
        " stopped": style_for_plain_segment(text, " stopped"),
        " starting": style_for_plain_segment(text, " starting"),
        " running": style_for_plain_segment(text, " running"),
        " waiting": style_for_plain_segment(text, " waiting"),
        " failed": style_for_plain_segment(text, " failed"),
        " unread": style_for_plain_segment(text, " unread"),
        " done": style_for_plain_segment(text, " done"),
    }
    assert label_styles == {
        " stopped": "dim",
        " starting": "bold #1a1a1a on #87D7FF",
        " running": "dim",
        " waiting": "dim",
        " failed": "dim",
        " unread": "bold #1a1a1a on #FFD700",
        " done": "dim",
    }


def test_update_agent_counts_uses_plain_metric_text() -> None:
    panel = AgentInfoPanel()

    captured: list[str] = []
    with patch.object(
        panel,
        "update",
        lambda text, **_kwargs: captured.append(text.plain),
    ):
        panel.update_agent_counts(1, 2, 3, 4, 5, 6, 10)
    assert captured, "panel.update_agent_counts did not refresh the display"
    plain = captured[-1]

    assert (
        "10 [3 running · 2 stopped · 4 waiting · 5 failed · 1 unread · 6 done]"
    ) in plain
    assert "Agents(" not in plain
    assert "#FFAF5F" not in plain
    assert " read" not in plain


def test_agent_count_strip_omits_zero_metric_types() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_agent_counts(
            unread=2,
            asking=0,
            running=3,
            waiting=0,
            failed=1,
            read=0,
            total=9,
        )

    plain = collect_text(panel)
    counts_prefix = plain.split(" · group:", 1)[0]

    assert plain.startswith("9 [3 running · 1 failed · 2 unread]")
    assert "stopped" not in counts_prefix
    assert "waiting" not in counts_prefix
    assert " done" not in counts_prefix


def test_agent_count_strip_keeps_zero_running_when_all_counts_are_zero() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_agent_counts(
            unread=0,
            asking=0,
            running=0,
            waiting=0,
            failed=0,
            read=0,
            total=5,
        )

    plain = collect_text(panel)
    counts_prefix = plain.split(" · group:", 1)[0]

    assert counts_prefix == "5 [0 running]"


def test_status_strip_uses_visible_running_count_and_omits_zero_queue() -> None:
    panel = AgentInfoPanel()
    panel._sase_agent_count = 12
    panel._running_count = 8
    panel._runner_queue_count = 0

    plain = collect_text(panel)

    assert plain.startswith("12 [8 running]")
    assert "queued" not in plain


def test_positive_queue_appears_inside_consolidated_status_strip() -> None:
    panel = AgentInfoPanel()
    panel._running_count = 10
    panel._runner_queue_count = 1
    panel._waiting_count = 4

    plain = collect_text(panel)

    assert "[10 running · 1 queued · 4 waiting]" in plain
    assert plain.count("[10 running") == 1
    assert "1 queue" not in plain.replace("1 queued", "")


def test_status_strip_styles_running_capacity_and_positive_queue() -> None:
    panel = AgentInfoPanel()
    panel._runner_queue_count = 7
    panel._read_count = 19
    panel._running_count = 8

    text = collect_rich_text(panel)
    running_count_index = text.plain.index("[8 running")
    running_label_index = text.plain.index(" running", running_count_index)
    queue_index = text.plain.index("7 queued")
    done_index = text.plain.index("19 done")
    assert style_at_plain_index(text, running_count_index + 1) == "bold #00D7AF"
    assert style_at_plain_index(text, running_label_index) == "dim"
    queue_style = style_at_plain_index(text, queue_index)
    waiting_style = panel._COUNT_STYLES["waiting"]
    assert queue_style == AGENT_COUNT_CHIP_QUEUED_STYLE
    assert queue_style != waiting_style
    done_style = style_at_plain_index(text, done_index)
    assert done_style == "bold #5FD7FF"
    assert queue_style != done_style

    panel._runner_queue_count = 0
    zero_text = collect_rich_text(panel)
    assert "queued" not in zero_text.plain


def test_running_count_style_is_constant_across_capacity_pressure() -> None:
    """The running count never encodes pressure; capacity lives in the gauge."""
    panel = AgentInfoPanel()
    running_styles = set()
    for running_count in [0, 5, 8, 10, 13]:
        panel._running_count = running_count
        text = collect_rich_text(panel)
        running_index = text.plain.index(f"[{running_count} running")
        running_styles.add(style_at_plain_index(text, running_index + 1))
        # The panel text no longer contains any `/<limit>` capacity fraction.
        assert "/10" not in text.plain
        assert "/" not in text.plain

    assert running_styles == {"bold #00D7AF"}


def test_update_runner_queue_count_caches_queue() -> None:
    panel = AgentInfoPanel()

    with patch.object(panel, "update"):
        panel.update_runner_queue_count(2)

    assert panel._runner_queue_count == 2
    assert not hasattr(panel, "_runner_slots_in_use")
    assert not hasattr(panel, "_runner_limit")
    assert not hasattr(panel, "_runner_occupied_capacity")
