"""Routing tests for saved agent group revival."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from sase.ace.tui.modals import ProjectSelectModal
from sase.ace.tui.modals.saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalModal,
    SavedAgentGroupRevivalResult,
)
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupPageWire,
    SavedAgentGroupSummaryWire,
)

from tests._agent_revive_helpers import FakeReviveApp, make_agent


class _ScreenCapture:
    def __init__(self) -> None:
        self.pushed: list[tuple[object, Any]] = []

    def push_screen(self, screen: object, callback: Any = None) -> None:
        self.pushed.append((screen, callback))


def test_agents_r_opens_saved_group_revival_panel() -> None:
    app = FakeReviveApp()
    capture = _ScreenCapture()
    app.app = capture  # type: ignore[attr-defined]
    agent = make_agent()
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with patch(
        "sase.ace.dismissed_agents.list_dismissed_agent_groups",
        return_value=SavedAgentGroupPageWire(groups=(), next_cursor=None),
    ):
        app._revive_agent()

    assert len(capture.pushed) == 1
    assert isinstance(capture.pushed[0][0], SavedAgentGroupRevivalModal)


def test_custom_search_result_opens_legacy_project_scope_flow() -> None:
    app = FakeReviveApp()
    capture = _ScreenCapture()
    app.app = capture  # type: ignore[attr-defined]
    agent = make_agent()
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with patch(
        "sase.ace.dismissed_agents.list_dismissed_agent_groups",
        return_value=SavedAgentGroupPageWire(groups=(_summary(),), next_cursor=None),
    ):
        app._revive_agent()

    callback = capture.pushed[0][1]
    with (
        patch(
            "sase.ace.tui.modals.project_select_modal.list_launchable_projects",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.modals.project_select_modal.find_all_changespecs",
            return_value=[],
        ),
    ):
        callback(SavedAgentGroupRevivalResult(action="custom_search"))

    assert len(capture.pushed) == 2
    assert isinstance(capture.pushed[1][0], ProjectSelectModal)


def test_saved_group_result_dispatches_to_phase_four_hook() -> None:
    app = FakeReviveApp()
    capture = _ScreenCapture()
    app.app = capture  # type: ignore[attr-defined]
    agent = make_agent()
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}
    revived_group_ids: list[str] = []
    app._revive_saved_agent_group = revived_group_ids.append  # type: ignore[method-assign]

    with patch(
        "sase.ace.dismissed_agents.list_dismissed_agent_groups",
        return_value=SavedAgentGroupPageWire(groups=(_summary(),), next_cursor=None),
    ):
        app._revive_agent()

    callback = capture.pushed[0][1]
    callback(
        SavedAgentGroupRevivalResult(
            action="revive_group",
            group_id="group-a",
        )
    )

    assert revived_group_ids == ["group-a"]


def _summary() -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id="group-a",
        created_at="2026-05-27T12:00:00Z",
        source="marked_agents",
        title="1 agent in backend",
        agent_count=1,
        top_level_agent_count=1,
        status_counts={"DONE": 1},
        project_names=("sase",),
        cl_names=("backend",),
    )
