"""Tests for syncing muted plan notifications to agent tags."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.agent_tags import MUTE_AGENT_TAG, load_agent_tags, save_agent_tags
from sase.ace.tui.actions.agents._notifications import AgentNotificationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import Notification


class _NotificationMuteTagApp(AgentNotificationMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self.invalidate_count = 0
        self.refresh_agents_display = MagicMock()

    def _invalidate_agent_panel_cache(self) -> None:
        self.invalidate_count += 1

    def _refresh_agents_display(
        self,
        *,
        list_changed: bool = False,
        defer_detail: bool = False,
    ) -> None:
        self.refresh_agents_display(
            list_changed=list_changed,
            defer_detail=defer_detail,
        )


def _agent(
    *,
    raw_suffix: str = "20260512094333",
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "PLAN",
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 5, 12, 9, 43, 33),
        raw_suffix=raw_suffix,
    )


def _notification(
    *,
    action: str = "PlanApproval",
    agent_timestamp: str = "20260512094333",
    agent_root_timestamp: str = "20260512090000",
) -> Notification:
    return Notification(
        id="n1",
        timestamp="2026-05-12T09:43:33",
        sender="plan",
        action=action,
        action_data={
            "agent_cl_name": "oo",
            "agent_timestamp": agent_timestamp,
            "agent_root_timestamp": agent_root_timestamp,
            "response_dir": "/tmp/response",
            "session_id": "session",
        },
    )


def test_plan_notification_mute_sets_mute_on_untagged_agent(
    tmp_path: Path,
) -> None:
    tag_file = tmp_path / "agent_tags.json"
    agent = _agent()
    app = _NotificationMuteTagApp([agent])

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        changed = app._sync_plan_notification_mute_tag(
            _notification(),
            muted=True,
        )

        assert changed is True
        assert agent.tag == MUTE_AGENT_TAG
        assert load_agent_tags() == {agent.identity: MUTE_AGENT_TAG}
        assert app.invalidate_count == 1
        app.refresh_agents_display.assert_called_once_with(
            list_changed=True,
            defer_detail=False,
        )


def test_plan_notification_mute_preserves_existing_in_memory_tag(
    tmp_path: Path,
) -> None:
    tag_file = tmp_path / "agent_tags.json"
    agent = _agent()
    agent.tag = "manual"
    app = _NotificationMuteTagApp([agent])

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        changed = app._sync_plan_notification_mute_tag(
            _notification(),
            muted=True,
        )

        assert changed is False
        assert agent.tag == "manual"
        assert load_agent_tags() == {}
        assert app.invalidate_count == 0
        app.refresh_agents_display.assert_not_called()


def test_plan_notification_unmute_clears_mute_tag(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    agent = _agent()
    agent.tag = MUTE_AGENT_TAG
    app = _NotificationMuteTagApp([agent])

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        assert save_agent_tags({agent.identity: MUTE_AGENT_TAG})

        changed = app._sync_plan_notification_mute_tag(
            _notification(),
            muted=False,
        )

        assert changed is True
        assert agent.tag is None
        assert load_agent_tags() == {}
        assert app.invalidate_count == 1
        app.refresh_agents_display.assert_called_once_with(
            list_changed=True,
            defer_detail=False,
        )


def test_plan_notification_unmute_preserves_non_mute_tag(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    agent = _agent()
    agent.tag = "manual"
    app = _NotificationMuteTagApp([agent])

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        assert save_agent_tags({agent.identity: "manual"})

        changed = app._sync_plan_notification_mute_tag(
            _notification(),
            muted=False,
        )

        assert changed is False
        assert agent.tag == "manual"
        assert load_agent_tags() == {agent.identity: "manual"}
        assert app.invalidate_count == 0
        app.refresh_agents_display.assert_not_called()


def test_plan_notification_mute_uses_root_timestamp_matching(
    tmp_path: Path,
) -> None:
    tag_file = tmp_path / "agent_tags.json"
    parent = _agent(
        raw_suffix="20260512090000",
        agent_type=AgentType.WORKFLOW,
        status="RUNNING",
    )
    child = _agent(raw_suffix="20260512094333", status="DONE")
    app = _NotificationMuteTagApp([parent, child])

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        changed = app._sync_plan_notification_mute_tag(
            _notification(),
            muted=True,
        )

        assert changed is True
        assert parent.tag == MUTE_AGENT_TAG
        assert child.tag is None
        assert load_agent_tags() == {parent.identity: MUTE_AGENT_TAG}


def test_non_plan_notification_is_ignored(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    agent = _agent()
    app = _NotificationMuteTagApp([agent])

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        changed = app._sync_plan_notification_mute_tag(
            _notification(action="UserQuestion"),
            muted=True,
        )

        assert changed is False
        assert agent.tag is None
        assert load_agent_tags() == {}
