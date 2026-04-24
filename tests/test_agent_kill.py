"""Tests for kill agent functionality."""

from __future__ import annotations

import asyncio

from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType

# --- Kill Agent Tests ---


def test_kill_process_group_process_already_dead() -> None:
    """Test _kill_process_group handles ProcessLookupError."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

    app = MockApp()

    with patch(
        "sase.ace.tui.actions.agents._killing.os.killpg", side_effect=ProcessLookupError
    ):
        result = app._kill_process_group(12345)
        assert result is True  # Still considered success


def test_kill_process_group_permission_error() -> None:
    """Test _kill_process_group handles PermissionError."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

    app = MockApp()

    with patch(
        "sase.ace.tui.actions.agents._killing.os.killpg", side_effect=PermissionError
    ):
        result = app._kill_process_group(12345)
        assert result is False  # Permission error is a failure
        assert len(app._notifications) == 1
        assert "Permission denied" in app._notifications[0][0]
        assert app._notifications[0][1] == "error"


def test_kill_running_agent_releases_workspace() -> None:
    """Test _kill_running_agent kills process and releases workspace."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

    app = MockApp()

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workspace_num=5,
        workflow="crs",
        pid=12345,
    )

    with (
        patch("sase.ace.tui.actions.agents._killing.os.killpg") as mock_killpg,
        patch("sase.running_field.release_workspace") as mock_release,
    ):
        app._kill_running_agent(agent)

        mock_killpg.assert_called_once_with(12345, 15)
        mock_release.assert_called_once_with("/tmp/test.gp", 5, "crs", "my_feature")
        assert len(app._notifications) == 1
        assert "Killed agent" in app._notifications[0][0]


def test_kill_hook_agent_marks_as_killed() -> None:
    """Test _kill_hook_agent kills process and marks hook as killed."""
    from sase.ace.changespec import ChangeSpec, HookEntry, HookStatusLine
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

    app = MockApp()

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        hook_command="bb_test",
        pid=12345,
        raw_suffix="fix_hook-12345-251230_151429",
    )

    mock_status_line = HookStatusLine(
        commit_entry_num="1",
        timestamp="251230_151429",
        status="RUNNING",
        suffix="fix_hook-12345-251230_151429",
        suffix_type="running_agent",
    )

    mock_hook = HookEntry(command="bb_test", status_lines=[mock_status_line])

    mock_cs = ChangeSpec(
        name="my_feature",
        description="Test",
        parent=None,
        cl="12345",
        status="Ready",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
        hooks=[mock_hook],
    )

    with (
        patch("sase.ace.tui.actions.agents._killing.os.killpg") as mock_killpg,
        patch("sase.ace.changespec.parse_project_file", return_value=[mock_cs]),
        patch("sase.ace.hooks.processes.mark_hook_agents_as_killed") as mock_mark,
        patch("sase.ace.hooks.update_changespec_hooks_field") as mock_update,
    ):
        mock_mark.return_value = [mock_hook]
        app._kill_hook_agent(agent)

        mock_killpg.assert_called_once_with(12345, 15)
        mock_mark.assert_called_once()
        mock_update.assert_called_once()
        assert len(app._notifications) == 1
        assert "Killed hook agent" in app._notifications[0][0]


def test_kill_mentor_agent_marks_as_killed() -> None:
    """Test _kill_mentor_agent kills process and marks mentor as killed."""
    from sase.ace.changespec import ChangeSpec, MentorEntry, MentorStatusLine
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

    app = MockApp()

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="mentor",
        mentor_profile="profile1",
        mentor_name="mentor1",
        pid=12345,
        raw_suffix="mentor_complete-12345-251230_151429",
    )

    mock_status_line = MentorStatusLine(
        timestamp="251231_120000",
        profile_name="profile1",
        mentor_name="mentor1",
        status="RUNNING",
        suffix="mentor_complete-12345-251230_151429",
        suffix_type="running_agent",
    )

    mock_mentor = MentorEntry(
        entry_id="1", profiles=["profile1"], status_lines=[mock_status_line]
    )

    mock_cs = ChangeSpec(
        name="my_feature",
        description="Test",
        parent=None,
        cl="12345",
        status="Ready",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
        mentors=[mock_mentor],
    )

    with (
        patch("sase.ace.tui.actions.agents._killing.os.killpg") as mock_killpg,
        patch("sase.ace.changespec.parse_project_file", return_value=[mock_cs]),
        patch("sase.ace.hooks.processes.mark_mentor_agents_as_killed") as mock_mark,
        patch("sase.ace.mentors.update_changespec_mentors_field") as mock_update,
    ):
        mock_mark.return_value = [mock_mentor]
        app._kill_mentor_agent(agent)

        mock_killpg.assert_called_once_with(12345, 15)
        mock_mark.assert_called_once()
        mock_update.assert_called_once()
        assert len(app._notifications) == 1
        assert "Killed mentor agent" in app._notifications[0][0]


def test_kill_crs_agent_marks_as_killed() -> None:
    """Test _kill_crs_agent kills process and marks comment as killed."""
    from sase.ace.changespec import ChangeSpec, CommentEntry
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

    app = MockApp()

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="crs",
        reviewer="critique",
        pid=12345,
        raw_suffix="crs-12345-251230_151429",
    )

    mock_comment = CommentEntry(
        reviewer="critique",
        file_path="~/.sase/comments/test.json",
        suffix="crs-12345-251230_151429",
        suffix_type="running_agent",
    )

    mock_cs = ChangeSpec(
        name="my_feature",
        description="Test",
        parent=None,
        cl="12345",
        status="Ready",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
        comments=[mock_comment],
    )

    with (
        patch("sase.ace.tui.actions.agents._killing.os.killpg") as mock_killpg,
        patch("sase.ace.changespec.parse_project_file", return_value=[mock_cs]),
        patch(
            "sase.ace.comments.operations.mark_comment_agents_as_killed"
        ) as mock_mark,
        patch("sase.ace.comments.update_changespec_comments_field") as mock_update,
    ):
        mock_mark.return_value = [mock_comment]
        app._kill_crs_agent(agent)

        mock_killpg.assert_called_once_with(12345, 15)
        mock_mark.assert_called_once()
        mock_update.assert_called_once()
        assert len(app._notifications) == 1
        assert "Killed CRS agent" in app._notifications[0][0]


def test_kill_agent_with_no_pid() -> None:
    """Test that agent with no PID shows warning and does nothing."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

    app = MockApp()

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=None,  # No PID
    )

    with patch("sase.ace.tui.actions.agents._killing.os.killpg") as mock_killpg:
        app._kill_hook_agent(agent)
        mock_killpg.assert_not_called()


def test_do_kill_agent_removes_in_memory_before_background_persistence() -> None:
    """Kill path should update UI state immediately and defer persistence work."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._agents_refresh_pending = False
            self._agents_refresh_scheduled = False
            self._agents_loading = False
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._pinned_agents = set()
            self._agents_with_children = []
            self._agents = []
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.refresh_calls: list[tuple[bool, bool]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            return

        def _build_panel_indices(self) -> None:
            return

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            self.refresh_calls.append((list_changed, defer_detail))

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self) -> None:
            return

    app = MockApp()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=12345,
        raw_suffix="fix_hook-12345-251230_151429",
    )
    app._agents = [agent]
    app._agents_with_children = [agent]

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(agent)

    assert app._agents == []
    assert agent.identity in app._dismissed_agents
    assert app.refresh_calls == [(True, True)]
    assert len(app._scheduled) == 1
    callback, args = app._scheduled[0]
    assert callback == app._run_kill_persistence_async
    assert args[0] == agent


def test_do_kill_agent_hook_persistence_runs_async() -> None:
    """Hook project-file writes are deferred to async persistence stage."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._agents_refresh_pending = False
            self._agents_refresh_scheduled = False
            self._agents_loading = False
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._pinned_agents = set()
            self._agents_with_children = []
            self._agents = []
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            return

        def _build_panel_indices(self) -> None:
            return

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            return

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self) -> None:
            return

    app = MockApp()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=12345,
        raw_suffix="fix_hook-12345-251230_151429",
    )
    app._agents = [agent]
    app._agents_with_children = [agent]

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(agent)

    with patch(
        "sase.ace.tui.actions.agents._killing._persist_hook_kill"
    ) as mock_persist_hook:
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))  # type: ignore[misc]
        mock_persist_hook.assert_called_once_with(agent)
