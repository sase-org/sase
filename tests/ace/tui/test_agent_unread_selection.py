"""Unread agent selection and acknowledgment tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup, panel_key_per_agent
from sase.ace.tui.widgets.agent_list import AgentList

from ._agent_unread_helpers import make_agent


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    return dismiss


class _SelectionEvent:
    def __init__(
        self,
        *,
        control: AgentList,
        index: int,
        group_key: tuple[str, ...] | None = None,
    ) -> None:
        self.control = control
        self.index = index
        self.attempt_number = None
        self.group_key = group_key


class _SelectionApp(EventHandlersMixin, AgentsMixinCore):
    def __init__(self, agents: list[Agent], *, patch_result: bool = True) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number: int | None = None
        self._agents = agents
        self._agent_panels_grouped = False
        self._panel_group = AgentPanelGroup.from_agents(agents)
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._patch_result = patch_result
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, Any]] = []
        self.notification_count_refresh_calls = 0
        self.artifact_file_viewer_guard_active = False
        self.notify = Mock()

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        if not self.artifact_file_viewer_guard_active:
            return False
        self.notify(
            "Close the artifact viewer before switching agents",
            severity="warning",
        )
        return True

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(self._agents)

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return self._patch_result

    def _refresh_agents_display(self, **kwargs: Any) -> None:
        self.refresh_calls.append(kwargs)

    def _refresh_notification_count(self) -> None:
        self.notification_count_refresh_calls += 1


def test_agent_row_selection_clears_unread_and_patches_row() -> None:
    agent = make_agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=0)
    )

    assert agent.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [agent]
    assert app.refresh_calls == []


def test_agent_row_selection_refreshes_when_patch_cannot_land() -> None:
    agent = make_agent(status="DONE")
    app = _SelectionApp([agent], patch_result=False)
    app._unread_completed_agent_ids.add(agent.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=0)
    )

    assert agent.identity not in app._unread_completed_agent_ids
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_same_index_agent_row_selection_clears_stale_banner_focus_unread() -> None:
    agent = make_agent(status="DONE")
    app = _SelectionApp([agent])
    app._current_group_key = ("demo",)
    app._unread_completed_agent_ids.add(agent.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=0)
    )

    assert app.current_idx == 0
    assert app._current_group_key is None
    assert agent.identity not in app._unread_completed_agent_ids


def test_banner_selection_does_not_clear_agent_unread() -> None:
    agent = make_agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(
            control=AgentList(id="agent-list-panel"),
            index=0,
            group_key=("demo",),
        )
    )

    assert agent.identity in app._unread_completed_agent_ids


def test_manual_unread_mouse_selection_preserves_selected_row() -> None:
    agent = make_agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=0)
    )

    assert agent.identity in app._unread_completed_agent_ids
    assert agent.identity in app._manual_unread_agent_ids
    assert app.patch_calls == []


def test_manual_unread_mouse_selection_arms_then_acknowledges_on_return() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = _SelectionApp([first, second])
    app._unread_completed_agent_ids.add(first.identity)
    app._manual_unread_agent_ids.add(first.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=1)
    )

    assert first.identity in app._unread_completed_agent_ids
    assert first.identity not in app._manual_unread_agent_ids

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=0)
    )

    assert first.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [first]


def test_agent_row_selection_guard_ignores_different_agent() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = _SelectionApp([first, second])
    app.artifact_file_viewer_guard_active = True

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=1)
    )

    assert app.current_idx == 0
    assert app._current_group_key is None
    app.notify.assert_called_once_with(
        "Close the artifact viewer before switching agents",
        severity="warning",
    )


def test_acknowledge_agent_unread_dismisses_matching_notification(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    agent = make_agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    assert app._acknowledge_agent_unread(agent)

    assert agent.identity not in app._unread_completed_agent_ids
    notification_dismiss.assert_called_once_with(
        [{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}]
    )
    assert app.notification_count_refresh_calls == 1


def test_acknowledge_agent_unread_filters_stale_cached_notification(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    agent = make_agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._notification_snapshot_cache = SimpleNamespace(
        notifications=[
            SimpleNamespace(
                id="n-agent",
                sender="user-agent",
                action="JumpToAgent",
                action_data={"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix},
                dismissed=False,
            )
        ]
    )

    assert app._acknowledge_agent_unread(agent)
    app._reconcile_unread_from_cached_notifications()

    assert agent.identity not in app._unread_completed_agent_ids
    assert app._notification_snapshot_cache.notifications == []
    assert app.notification_count_refresh_calls == 1


def test_acknowledge_agent_unread_does_not_dismiss_manual_guard(
    notification_dismiss: Mock,
) -> None:
    agent = make_agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    assert not app._acknowledge_agent_unread(agent)

    assert agent.identity in app._unread_completed_agent_ids
    notification_dismiss.assert_not_called()
    assert app.notification_count_refresh_calls == 0


def test_dismissed_agent_helper_clears_manual_unread_and_cache(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    agent = make_agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)
    app._notification_snapshot_cache = SimpleNamespace(
        notifications=[
            SimpleNamespace(
                id="n-agent",
                sender="user-agent",
                action="JumpToAgent",
                action_data={"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix},
                dismissed=False,
            )
        ]
    )
    app._last_unread_ids = {"n-agent"}

    count = app._dismiss_agent_completion_notifications_for_dismissed_agents([agent])

    assert count == 1
    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app._notification_snapshot_cache.notifications == []
    assert app._last_unread_ids == set()
    notification_dismiss.assert_called_once_with(
        [{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}]
    )
    assert app.notification_count_refresh_calls == 1


def test_dismissed_agent_helper_is_idempotent(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.side_effect = [1, 0]
    agent = make_agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._notification_snapshot_cache = SimpleNamespace(
        notifications=[
            SimpleNamespace(
                id="n-agent",
                sender="user-agent",
                action="JumpToAgent",
                action_data={"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix},
                dismissed=False,
            )
        ]
    )

    assert app._dismiss_agent_completion_notifications_for_dismissed_agents([agent])
    assert not app._dismiss_agent_completion_notifications_for_dismissed_agents([agent])

    assert app._unread_completed_agent_ids == set()
    assert app._notification_snapshot_cache.notifications == []
    assert notification_dismiss.call_count == 2
    assert app.notification_count_refresh_calls == 1
