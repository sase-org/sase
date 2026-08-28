"""Tests for resolving notifications to agent rows and their refreshes."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._notification_navigation import (
    find_agent_for_notification,
)
from sase.ace.tui.actions.agents._notification_utils import (
    request_notification_agents_refresh,
)
from sase.ace.tui.models.agent import Agent, AgentType

from tests._notification_toasts_helpers import (
    _FakeApp,
    _make,
    _patch_snapshot,
    _snapshot,
)


class TestDisappearedReviewRefresh:
    """A review row leaving the store refreshes only the agents it names."""

    def test_disappeared_plan_reviews_schedule_one_exact_artifact_delta(
        self,
        tmp_path: Path,
    ) -> None:
        app = _FakeApp()
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        agent = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="review-agent",
            project_file="/tmp/test.sase",
            status="TALE",
            start_time=datetime(2026, 7, 22, 9, 0, 0),
            raw_suffix="20260722090000",
            artifacts_dir=str(artifacts_dir),
        )
        app._agents = [agent]
        action_data = {
            "agent_cl_name": agent.cl_name,
            "agent_root_timestamp": agent.raw_suffix or "",
        }
        tale = _make(
            id="tale-review",
            action="PlanApproval",
            action_data=action_data,
            muted=True,
        )
        epic = _make(
            id="epic-review",
            action="EpicApproval",
            action_data=action_data,
        )
        app._notification_snapshot_cache = _snapshot([tale, epic])
        scheduled: list[tuple[tuple[Path, ...], str]] = []
        broad_refreshes: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((tuple(dirs), source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad_refreshes.append((source, latest_only))
        )

        with (
            _patch_snapshot([]) as read_snapshot,
            patch("sase.notifications.load_notifications") as load_notifications,
        ):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert scheduled == [((artifacts_dir,), "notification")]
        assert broad_refreshes == []
        assert app.notify.call_count == 0
        assert app._bell_rung == 0
        load_notifications.assert_not_called()
        assert read_snapshot.call_args.args[0] is False

    def test_unrelated_disappeared_notification_does_not_refresh(self) -> None:
        app = _FakeApp()
        unrelated = _make(id="question", action="UserQuestion")
        app._notification_snapshot_cache = _snapshot([unrelated])
        scheduled: list[tuple[object, str]] = []
        broad_refreshes: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((dirs, source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad_refreshes.append((source, latest_only))
        )

        with _patch_snapshot([]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert scheduled == []
        assert broad_refreshes == []

    def test_disappeared_plan_review_uses_broad_fallback_without_exact_agent(
        self,
    ) -> None:
        app = _FakeApp()
        review = _make(
            id="missing-agent-review",
            action="PlanApproval",
            action_data={"agent_cl_name": "not-loaded"},
        )
        app._notification_snapshot_cache = _snapshot([review])
        scheduled: list[tuple[object, str]] = []
        broad_refreshes: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((dirs, source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad_refreshes.append((source, latest_only))
        )

        with _patch_snapshot([]):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is False
        assert scheduled == []
        assert broad_refreshes == [("notification", True)]


class TestNotificationAgentTargeting:
    """Section 2: notification targeting resolves the complete loaded roster.

    ``find_agent_for_notification`` and the completion-delta lookup used by
    ``request_notification_agents_refresh`` must resolve against the
    complete loaded roster (``_agents_with_children``), not just the
    currently visible/folded/filtered ``_agents`` projection, so a
    completion for a hidden row still schedules a bounded exact delta
    instead of falling back to a broad load.
    """

    def _install_capture(
        self, app: _FakeApp
    ) -> tuple[list[tuple[tuple[Path, ...], str]], list[tuple[str, bool]]]:
        scheduled: list[tuple[tuple[Path, ...], str]] = []
        broad: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((tuple(dirs), source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad.append((source, latest_only))
        )
        return scheduled, broad

    def test_clan_folded_completion_schedules_exact_delta_not_broad(
        self, tmp_path: Path
    ) -> None:
        """A completed agent hidden behind a collapsed clan still resolves."""
        app = _FakeApp()
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        cl_name = "clan-child"
        raw_suffix = "20260722090000"
        child = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=cl_name,
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2026, 7, 22, 9, 0, 0),
            raw_suffix=raw_suffix,
            artifacts_dir=str(artifacts_dir),
            agent_clan="clan-a",
        )
        clan_container = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="clan-a",
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2026, 7, 22, 9, 0, 0),
            raw_suffix=None,
            is_clan_container=True,
            agent_clan="clan-a",
        )
        # The visible/filtered projection only shows the collapsed clan
        # container row; the complete roster still has the real child.
        app._agents = [clan_container]
        app._agents_with_children = [clan_container, child]  # type: ignore[attr-defined]
        completion = _make(
            action="JumpToAgent",
            sender="user-agent",
            action_data={"cl_name": cl_name, "raw_suffix": raw_suffix},
        )
        app._notification_snapshot_cache = _snapshot([completion])
        scheduled, broad = self._install_capture(app)

        request_notification_agents_refresh(app)

        assert scheduled == [((artifacts_dir,), "notification")]
        assert broad == []

    def test_search_hidden_completion_schedules_exact_delta_not_broad(
        self, tmp_path: Path
    ) -> None:
        """A completed agent excluded by the active search query still resolves."""
        app = _FakeApp()
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        cl_name = "hidden-agent"
        raw_suffix = "20260722091500"
        hidden = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=cl_name,
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2026, 7, 22, 9, 0, 0),
            raw_suffix=raw_suffix,
            artifacts_dir=str(artifacts_dir),
        )
        # A search query filtered `hidden` out of the visible projection,
        # but the complete roster (used to restore the query) keeps it.
        app._agents = []
        app._agents_with_children = [hidden]  # type: ignore[attr-defined]
        completion = _make(
            action="JumpToAgent",
            sender="user-agent",
            action_data={"cl_name": cl_name, "raw_suffix": raw_suffix},
        )
        app._notification_snapshot_cache = _snapshot([completion])
        scheduled, broad = self._install_capture(app)

        request_notification_agents_refresh(app)

        assert scheduled == [((artifacts_dir,), "notification")]
        assert broad == []

    def test_find_agent_for_notification_resolves_via_agents_with_children(
        self,
    ) -> None:
        app = _FakeApp()
        cl_name = "hidden-agent"
        raw_suffix = "20260722091500"
        hidden = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=cl_name,
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2026, 7, 22, 9, 0, 0),
            raw_suffix=raw_suffix,
        )
        app._agents = []
        app._agents_with_children = [hidden]  # type: ignore[attr-defined]
        notification = _make(
            action="PlanApproval",
            action_data={
                "agent_cl_name": cl_name,
                "agent_root_timestamp": raw_suffix,
            },
        )

        assert find_agent_for_notification(app, notification) is hidden

    def test_find_agent_for_notification_excludes_clan_containers(self) -> None:
        app = _FakeApp()
        cl_name = "clan-child"
        raw_suffix = "20260722090000"
        # This synthetic clan-container row would otherwise satisfy the
        # notification's identity fields; only the is_clan_container
        # exclusion should keep it from being returned.
        clan_container = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=cl_name,
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2026, 7, 22, 9, 0, 0),
            raw_suffix=raw_suffix,
            is_clan_container=True,
            agent_clan="clan-a",
        )
        app._agents = [clan_container]
        app._agents_with_children = [clan_container]  # type: ignore[attr-defined]
        notification = _make(
            action="PlanApproval",
            action_data={
                "agent_cl_name": cl_name,
                "agent_root_timestamp": raw_suffix,
            },
        )

        assert find_agent_for_notification(app, notification) is None

    def test_unloaded_completion_resolves_via_raw_suffix(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        raw_suffix = "20260828140403"
        artifact_dir = (
            sase_home
            / "projects"
            / "demo"
            / "artifacts"
            / "ace-run"
            / "202608"
            / "28"
            / raw_suffix
        )
        artifact_dir.mkdir(parents=True)
        app = _FakeApp()
        app._agents = []
        app._agents_with_children = []  # type: ignore[attr-defined]
        completion = _make(
            action="JumpToAgent",
            sender="user-agent",
            action_data={"cl_name": "0fn--code", "raw_suffix": raw_suffix},
        )
        scheduled, broad = self._install_capture(app)

        request_notification_agents_refresh(app, notifications=[completion])

        assert scheduled == [((artifact_dir,), "notification")]
        assert broad == []

    def test_unresolvable_completion_falls_back_to_broad(self) -> None:
        app = _FakeApp()
        completion = _make(
            action="JumpToAgent",
            sender="user-agent",
            action_data={"cl_name": "missing", "raw_suffix": "20260828140403"},
        )
        scheduled, broad = self._install_capture(app)

        request_notification_agents_refresh(app, notifications=[completion])

        assert scheduled == []
        assert broad == [("notification", True)]

    def test_unresolvable_completion_skips_broad_when_disallowed(self) -> None:
        app = _FakeApp()
        completion = _make(
            action="JumpToAgent",
            sender="user-agent",
            action_data={"cl_name": "missing", "raw_suffix": "20260828140403"},
        )
        scheduled, broad = self._install_capture(app)

        request_notification_agents_refresh(
            app,
            notifications=[completion],
            allow_broad_fallback=False,
        )

        assert scheduled == []
        assert broad == []

    def test_one_new_completion_does_not_rescan_unread_inbox(
        self,
        tmp_path: Path,
    ) -> None:
        app = _FakeApp()
        new_dir = tmp_path / "new"
        old_dir = tmp_path / "old"
        new_dir.mkdir()
        old_dir.mkdir()
        new_agent = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="new-agent",
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2026, 8, 28, 14, 4, 3),
            raw_suffix="20260828140403",
            artifacts_dir=str(new_dir),
        )
        old_agent = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="old-agent",
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2026, 8, 28, 12, 0, 0),
            raw_suffix="20260828120000",
            artifacts_dir=str(old_dir),
        )
        app._agents = [new_agent, old_agent]
        app._agents_with_children = [new_agent, old_agent]  # type: ignore[attr-defined]
        unread = [
            _make(
                action="JumpToAgent",
                sender="user-agent",
                action_data={
                    "cl_name": f"old-agent-{index}",
                    "raw_suffix": f"202608281200{index:02d}",
                },
            )
            for index in range(20)
        ]
        unread.append(
            _make(
                action="JumpToAgent",
                sender="user-agent",
                action_data={
                    "cl_name": old_agent.cl_name,
                    "raw_suffix": old_agent.raw_suffix or "",
                },
            )
        )
        new_completion = _make(
            action="JumpToAgent",
            sender="user-agent",
            action_data={
                "cl_name": new_agent.cl_name,
                "raw_suffix": new_agent.raw_suffix or "",
            },
        )
        app._notification_snapshot_cache = _snapshot([*unread, new_completion])
        scheduled, broad = self._install_capture(app)

        request_notification_agents_refresh(app, notifications=[new_completion])

        assert scheduled == [((new_dir,), "notification")]
        assert broad == []

    def test_scheduled_poll_exact_delta_runs_off_agents_tab(
        self,
        tmp_path: Path,
    ) -> None:
        app = _FakeApp()
        app.current_tab = "axe"  # type: ignore[attr-defined]
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        agent = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="0fn--code",
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2026, 8, 28, 14, 4, 3),
            raw_suffix="20260828140403",
            artifacts_dir=str(artifacts_dir),
        )
        app._agents_with_children = [agent]  # type: ignore[attr-defined]
        completion = _make(
            action="JumpToAgent",
            sender="user-agent",
            action_data={
                "cl_name": agent.cl_name,
                "raw_suffix": agent.raw_suffix or "",
            },
        )
        scheduled, broad = self._install_capture(app)

        with _patch_snapshot([completion]):
            asyncio.run(app._run_scheduled_notification_poll(source="watcher"))

        assert scheduled == [((artifacts_dir,), "notification")]
        assert broad == []

    def test_scheduled_poll_broad_fallback_is_tab_gated(self) -> None:
        app = _FakeApp()
        app.current_tab = "axe"  # type: ignore[attr-defined]
        completion = _make(
            action="JumpToAgent",
            sender="user-agent",
            action_data={"cl_name": "missing", "raw_suffix": "20260828140403"},
        )
        scheduled, broad = self._install_capture(app)

        with _patch_snapshot([completion]):
            asyncio.run(app._run_scheduled_notification_poll(source="watcher"))

        assert scheduled == []
        assert broad == []

        app.current_tab = "agents"  # type: ignore[attr-defined]
        app._delivered_notification_activity_cursors.clear()
        scheduled.clear()
        broad.clear()
        with _patch_snapshot([completion]):
            asyncio.run(app._run_scheduled_notification_poll(source="watcher"))

        assert scheduled == []
        assert broad == [("notification", True)]
