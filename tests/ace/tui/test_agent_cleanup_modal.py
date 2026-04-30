"""Tests for the Agents cleanup panel shell."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.ace.tui.modals import (
    AgentCleanupModal,
    AgentCleanupPanelState,
    AgentCleanupResult,
)


def _state(**overrides: Any) -> AgentCleanupPanelState:
    base = AgentCleanupPanelState(
        focused_panel_label="@fix",
        panel_running_count=1,
        panel_completed_count=2,
        panel_failed_count=1,
        all_running_count=3,
        all_completed_count=4,
        all_failed_count=1,
        marked_count=2,
        group_count=5,
        tag_count=2,
    )
    return replace(base, **overrides)


def test_agent_cleanup_modal_action_availability() -> None:
    modal = AgentCleanupModal(
        _state(
            panel_running_count=0,
            panel_completed_count=0,
            marked_count=0,
            group_count=0,
        )
    )

    rows = {row.action: row for row in modal._rows}
    assert rows["dismiss_panel_done"].enabled is False
    assert rows["kill_panel"].enabled is False
    assert rows["marked"].enabled is False
    assert rows["group"].enabled is False
    assert rows["dismiss_all_done"].enabled is True
    assert rows["kill_all"].enabled is True
    assert rows["tag"].enabled is False
    assert rows["custom"].enabled is False


def test_agent_cleanup_modal_selected_result(monkeypatch: Any) -> None:
    modal = AgentCleanupModal(_state())
    dismissed: list[AgentCleanupResult | None] = []
    monkeypatch.setattr(modal, "dismiss", dismissed.append)

    modal.action_kill_panel()

    assert dismissed == [AgentCleanupResult(action="kill_panel")]


def test_agent_cleanup_modal_disabled_action_does_not_dismiss(monkeypatch: Any) -> None:
    modal = AgentCleanupModal(_state(marked_count=0))
    dismissed: list[AgentCleanupResult | None] = []
    monkeypatch.setattr(modal, "dismiss", dismissed.append)

    modal.action_marked()

    assert dismissed == []
