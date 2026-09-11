"""Tests for Agents-tab info panel filter rendering and click handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from rich.text import Text

from ._agent_info_panel_helpers import (
    AgentInfoPanel,
    collect_rich_text,
    collect_text,
    style_for_plain_segment,
)


def test_update_search_query_falls_back_to_plain_gold_without_rich() -> None:
    """Off-flag (or no ``rich``), the legacy plain-gold rendering is used."""
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_search_query("status:FAILED", seeded=False)

    text = collect_rich_text(panel)

    assert "filter: status:FAILED" in text.plain
    assert style_for_plain_segment(text, "status:FAILED") == "bold #FFD700"
    assert panel._search_query_click_span is None


def test_update_search_query_renders_rich_query_with_match_count() -> None:
    """On-flag (sase-zf.4), the highlighted canonical query plus N/M shows."""
    panel = AgentInfoPanel()
    highlighted = Text("status:FAILED", style="bold #FF5F5F")
    with patch.object(panel, "update"):
        panel.update_search_query(
            "status:FAILED",
            rich=highlighted,
            match_count=(3, 12),
        )

    text = collect_rich_text(panel)

    assert "filter: status:FAILED  3/12" in text.plain
    assert panel._search_query_click_span is not None


def test_update_search_query_seeded_tag_follows_rich_segment() -> None:
    panel = AgentInfoPanel()
    highlighted = Text("project:demo")
    with patch.object(panel, "update"):
        panel.update_search_query(
            "project:demo",
            seeded=True,
            rich=highlighted,
            match_count=(1, 1),
        )

    plain = collect_text(panel)

    assert "filter: project:demo seeded  1/1" in plain


def test_search_query_click_span_covers_only_the_query_segment() -> None:
    panel = AgentInfoPanel()
    panel._sase_agent_count = 5
    highlighted = Text("status:FAILED")
    with patch.object(panel, "update"):
        panel.update_search_query("status:FAILED", rich=highlighted, match_count=(1, 5))
    text = collect_rich_text(panel)

    assert panel._search_query_click_span is not None
    start, end = panel._search_query_click_span
    assert text.plain[start:end] == "status:FAILED  1/5"


def test_click_inside_query_segment_posts_filter_clicked() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_search_query(
            "status:FAILED", rich=Text("status:FAILED"), match_count=(1, 5)
        )
    collect_rich_text(panel)
    assert panel._search_query_click_span is not None
    start, _end = panel._search_query_click_span

    posted: list[object] = []
    with patch.object(
        panel, "post_message", side_effect=lambda msg: posted.append(msg)
    ):
        event = SimpleNamespace(x=start, stop=lambda: None)
        panel.on_click(event)  # type: ignore[arg-type]

    assert len(posted) == 1
    assert isinstance(posted[0], AgentInfoPanel.FilterClicked)


def test_click_outside_query_segment_does_not_post() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_search_query(
            "status:FAILED", rich=Text("status:FAILED"), match_count=(1, 5)
        )
    collect_rich_text(panel)

    with patch.object(panel, "post_message") as post_message:
        event = SimpleNamespace(x=0, stop=lambda: None)
        panel.on_click(event)  # type: ignore[arg-type]

    post_message.assert_not_called()


def test_click_without_active_filter_is_a_no_op() -> None:
    panel = AgentInfoPanel()
    collect_rich_text(panel)
    assert panel._search_query_click_span is None

    with patch.object(panel, "post_message") as post_message:
        event = SimpleNamespace(x=10, stop=lambda: None)
        panel.on_click(event)  # type: ignore[arg-type]

    post_message.assert_not_called()
