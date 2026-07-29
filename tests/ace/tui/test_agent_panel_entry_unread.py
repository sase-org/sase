"""Unread acknowledgment when descending from whole-panel focus."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from sase.ace.tui.models.agent import Agent

from ._agent_panel_collapse_helpers import (
    AgentPanelUnreadEntryApp,
    make_agent,
)

_STOP_TIME = datetime(2026, 7, 15, 12, 5, 0)


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=1)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    return dismiss


def _entry_app() -> tuple[AgentPanelUnreadEntryApp, Agent, Agent]:
    remembered = make_agent(
        name="raw-first",
        project="zeta",
        tribe="alpha",
        status="DONE",
        stop_time=_STOP_TIME,
    )
    first_rendered = make_agent(
        name="render-first",
        project="alpha",
        tribe="alpha",
        status="DONE",
        stop_time=_STOP_TIME,
    )
    app = AgentPanelUnreadEntryApp(
        [remembered, first_rendered],
        focused_key="alpha",
    )
    app._expanded_panel_focus = True
    return app, remembered, first_rendered


def test_l_acknowledges_first_panel_entry_row(
    notification_dismiss: Mock,
) -> None:
    app, _remembered, first_rendered = _entry_app()
    app._unread_completed_agent_ids.add(first_rendered.identity)

    app.action_expand_or_layout()

    assert app.current_idx == 1
    assert first_rendered.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [first_rendered]
    assert app.notification_count_refresh_calls == 1
    notification_dismiss.assert_called_once_with(
        [
            {
                "cl_name": first_rendered.cl_name,
                "raw_suffix": first_rendered.raw_suffix,
            }
        ]
    )


def test_l_acknowledges_remembered_panel_entry_row(
    notification_dismiss: Mock,
) -> None:
    app, remembered, _first_rendered = _entry_app()
    app._panel_selection_memory["alpha"] = ("agent", 0)
    app._unread_completed_agent_ids.add(remembered.identity)

    app.action_expand_or_layout()

    assert app.current_idx == 0
    assert remembered.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [remembered]
    notification_dismiss.assert_called_once()


def test_escape_acknowledges_panel_entry_row(
    notification_dismiss: Mock,
) -> None:
    app, _remembered, first_rendered = _entry_app()
    app._unread_completed_agent_ids.add(first_rendered.identity)

    assert app._exit_expanded_panel_focus() is True

    assert app.current_idx == 1
    assert first_rendered.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [first_rendered]
    notification_dismiss.assert_called_once()


def test_banner_panel_entry_does_not_acknowledge_agent(
    notification_dismiss: Mock,
) -> None:
    unread = make_agent(
        name="one",
        project="one",
        tribe="research",
        status="DONE",
        stop_time=_STOP_TIME,
    )
    app = AgentPanelUnreadEntryApp(
        [
            unread,
            make_agent(name="two", project="two", tribe="research"),
        ],
        focused_key="research",
    )
    banner = app._all_known_group_keys()[0]
    app._group_fold_registry.for_panel("research").collapse(banner)
    app._panel_selection_memory["research"] = ("banner", banner)
    app._unread_completed_agent_ids.add(unread.identity)
    app._expanded_panel_focus = True

    app.action_expand_or_layout()

    assert app._current_group_key == banner
    assert unread.identity in app._unread_completed_agent_ids
    assert app.patch_calls == []
    notification_dismiss.assert_not_called()


def test_panel_entry_preserves_manually_unread_row(
    notification_dismiss: Mock,
) -> None:
    app, _remembered, first_rendered = _entry_app()
    app._unread_completed_agent_ids.add(first_rendered.identity)
    app._manual_unread_agent_ids.add(first_rendered.identity)

    app.action_expand_or_layout()

    assert first_rendered.identity in app._unread_completed_agent_ids
    assert first_rendered.identity in app._manual_unread_agent_ids
    assert app.patch_calls == []
    notification_dismiss.assert_not_called()
