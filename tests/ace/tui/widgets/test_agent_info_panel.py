"""Tests for the Agents-tab info panel rendering."""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.keymaps import key_display_name, load_keymap_registry
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel

_DEFAULT_GROUPING_KEY = key_display_name(
    load_keymap_registry({}).app.cycle_grouping_mode
)


def _collect_text(panel: AgentInfoPanel) -> str:
    captured: list[str] = []
    with patch.object(panel, "update", lambda text: captured.append(text.plain)):
        panel._update_display()
    assert captured, "panel._update_display did not invoke self.update()"
    return captured[-1]


def _collect_rich_text(panel: AgentInfoPanel) -> Text:
    captured: list[Text] = []
    with patch.object(panel, "update", lambda text: captured.append(text)):
        panel._update_display()
    assert captured, "panel._update_display did not invoke self.update()"
    return captured[-1]


def _style_for_plain_segment(text: Text, segment: str) -> str:
    start = text.plain.index(segment)
    end = start + len(segment)
    matching = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]
    assert matching, f"no Rich style span found for {segment!r}"
    return matching[-1]


def test_grouping_badge_renders_by_project_when_unset() -> None:
    """The badge always renders, treating an empty label as ``by project``."""
    panel = AgentInfoPanel()
    plain = _collect_text(panel)
    assert f"[group: by project ({_DEFAULT_GROUPING_KEY})]" in plain


def test_agent_count_strip_renders_total_before_agents_label() -> None:
    panel = AgentInfoPanel()
    panel._position = 2
    panel._total = 12
    panel._unread_count = 3
    panel._asking_count = 2
    panel._running_count = 5
    panel._waiting_count = 2
    panel._failed_count = 1
    panel._read_count = 0
    panel._visible_agent_count = 12

    plain = _collect_text(panel)

    assert plain.startswith(
        "12 Agents [2 asking · 5 running · 2 waiting · 1 failed · 3 unread]"
    )
    assert "Agents: 2/12" not in plain


def test_agent_count_numbers_have_rich_styles() -> None:
    panel = AgentInfoPanel()
    panel._visible_agent_count = 20
    panel._asking_count = 31
    panel._running_count = 42
    panel._waiting_count = 53
    panel._unread_count = 64
    panel._read_count = 75
    panel._failed_count = 86

    text = _collect_rich_text(panel)

    count_styles = {
        "total": _style_for_plain_segment(text, "20"),
        "asking": _style_for_plain_segment(text, "31"),
        "running": _style_for_plain_segment(text, "42"),
        "waiting": _style_for_plain_segment(text, "53"),
        "failed": _style_for_plain_segment(text, "86"),
        "unread": _style_for_plain_segment(text, "64"),
        "read": _style_for_plain_segment(text, "75"),
    }
    assert count_styles == {
        "total": "bold #5FAFFF",
        "asking": "bold #FFAF00",
        "running": "bold #00D7AF",
        "waiting": "bold #AF87FF",
        "failed": "bold #FF5F5F",
        "unread": "bold #FFAF5F",
        "read": "bold #BCBCBC",
    }


def test_update_agent_counts_uses_plain_metric_text() -> None:
    panel = AgentInfoPanel()

    captured: list[str] = []
    with patch.object(panel, "update", lambda text: captured.append(text.plain)):
        panel.update_agent_counts(1, 2, 3, 4, 5, 0, 10)
    assert captured, "panel.update_agent_counts did not refresh the display"
    plain = captured[-1]

    assert "10 Agents [2 asking · 3 running · 4 waiting · 5 failed · 1 unread]" in plain
    assert "Agents(" not in plain
    assert "#FFAF5F" not in plain


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

    plain = _collect_text(panel)
    counts_prefix = plain.split("   [group:", 1)[0]

    assert plain.startswith("9 Agents [3 running · 1 failed · 2 unread]")
    assert "asking" not in counts_prefix
    assert "waiting" not in counts_prefix
    assert " read" not in counts_prefix


def test_agent_count_strip_omits_metrics_section_when_all_counts_are_zero() -> None:
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

    plain = _collect_text(panel)
    counts_prefix = plain.split("   [group:", 1)[0]

    assert counts_prefix == "5 Agents"


def test_grouping_badge_renders_label_after_update() -> None:
    panel = AgentInfoPanel()
    panel._grouping_mode = "by status"
    plain = _collect_text(panel)
    assert f"[group: by status ({_DEFAULT_GROUPING_KEY})]" in plain


def test_grouping_badge_renders_by_date_label() -> None:
    panel = AgentInfoPanel()
    panel._grouping_mode = "by date"
    plain = _collect_text(panel)
    assert f"[group: by date ({_DEFAULT_GROUPING_KEY})]" in plain


def test_grouping_badge_suppressed_while_loading() -> None:
    """Loading state short-circuits before the badge segment is emitted."""
    panel = AgentInfoPanel()
    panel._loading = True
    plain = _collect_text(panel)
    assert "group:" not in plain


def test_count_strip_suppressed_while_loading() -> None:
    panel = AgentInfoPanel()
    panel._loading = True
    panel._unread_count = 3
    panel._asking_count = 2
    panel._running_count = 5
    panel._waiting_count = 2
    panel._failed_count = 1
    panel._read_count = 2
    panel._visible_agent_count = 12

    plain = _collect_text(panel)

    assert plain == "Agents: …"
    assert "unread" not in plain
    assert "failed" not in plain
