"""Tests for Agents-tab info panel badges and loading states."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.keymaps import load_keymap_registry

from ._agent_info_panel_helpers import (
    DEFAULT_GROUPING_KEY,
    DEFAULT_VIEW_KEY,
    AgentInfoPanel,
    collect_rich_text,
    collect_text,
    style_for_plain_segment,
)


def test_grouping_badge_renders_by_project_when_unset() -> None:
    """The badge always renders, treating an empty label as ``by project``."""
    panel = AgentInfoPanel()
    plain = collect_text(panel)
    assert f"group: by project ({DEFAULT_GROUPING_KEY})" in plain
    assert "[group" not in plain


def test_info_panel_never_renders_neighbors_badge() -> None:
    panel = AgentInfoPanel()
    panel._sase_agent_count = 5

    plain = collect_text(panel)

    assert "neighbors:" not in plain


def test_grouping_badge_renders_label_after_update() -> None:
    panel = AgentInfoPanel()
    panel._grouping_mode = "by status"
    plain = collect_text(panel)
    assert f"group: by status ({DEFAULT_GROUPING_KEY})" in plain
    assert "[group" not in plain


def test_grouping_badge_renders_by_date_label() -> None:
    panel = AgentInfoPanel()
    panel._grouping_mode = "by date"
    plain = collect_text(panel)
    assert f"group: by date ({DEFAULT_GROUPING_KEY})" in plain
    assert "[group" not in plain


def test_grouping_badge_omits_unbound_key_hint() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.set_keymap_registry(
            load_keymap_registry(
                {"keymaps": {"app": {"choose_agent_grouping": "unbound"}}}
            )
        )

    plain = collect_text(panel)

    assert "group: by project" in plain
    assert "group: by project (" not in plain
    assert "[group" not in plain


def test_summary_view_badge_is_visible_and_gold() -> None:
    panel = AgentInfoPanel()
    panel._view_mode = "summary"

    text = collect_rich_text(panel)

    assert "view: summary" in text.plain
    assert "[view" not in text.plain
    assert style_for_plain_segment(text, "summary") == "bold #FFD75F"


def test_view_badge_renders_picker_key_when_available() -> None:
    panel = AgentInfoPanel()
    panel._view_mode = "file"
    panel._view_picker_available = True

    plain = collect_text(panel)

    assert f"view: file ({DEFAULT_VIEW_KEY})" in plain
    assert "[view" not in plain


def test_view_badge_omits_picker_key_when_unavailable_or_unbound() -> None:
    panel = AgentInfoPanel()
    panel._view_mode = "file"
    panel._view_picker_available = False

    assert "view: file" in collect_text(panel)
    assert "[view" not in collect_text(panel)

    with patch.object(panel, "update"):
        panel.set_keymap_registry(
            load_keymap_registry({"keymaps": {"app": {"choose_agent_view": "unbound"}}})
        )
    panel._view_picker_available = True

    plain = collect_text(panel)
    assert "view: file" in plain
    assert "[view" not in plain


def test_grouping_badge_suppressed_while_loading() -> None:
    """Loading state short-circuits before the badge segment is emitted."""
    panel = AgentInfoPanel()
    panel._loading = True
    plain = collect_text(panel)
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
    panel._sase_agent_count = 12

    plain = collect_text(panel)

    assert plain == "Agents: …"
    assert "unread" not in plain
    assert "failed" not in plain
