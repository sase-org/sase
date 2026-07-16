"""Tests for killing waiting agents and cleaning up stale markers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from sase.agent.names._common import NamedAgent
from sase.agent.running import kill_named_agent
from tests._kill_named_agent_dismiss_helpers import (
    _isolated_dismissed_index as _isolated_dismissed_index,
)
from tests._kill_named_agent_dismiss_helpers import (
    append_question,
    notifications_by_id,
    patch_home,
    setup_waiting_agent,
    successful_user_kill,
)


def test_kill_named_agent_cleans_up_and_dismisses_when_pid_missing(
    tmp_path: Path,
    isolated_dismissed_index: Path,
) -> None:
    project_dir = tmp_path / ".sase" / "projects" / "myproj"
    artifacts_dir = project_dir / "artifacts" / "ace-run" / "20260510140000"
    artifacts_dir.mkdir(parents=True)
    project_file = project_dir / "myproj.sase"
    project_file.write_text("# Test Project\n\nNAME: feature_x\nSTATUS: Wip\n")
    (artifacts_dir / "waiting.json").write_text(
        json.dumps({"cl_name": "feature_x"}), encoding="utf-8"
    )
    append_question(
        notification_id="stale-question",
        cl_name="feature_x",
        child_timestamp="20260510140001",
        root_timestamp="20260510140000",
    )

    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.agent.running.update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        result = kill_named_agent("my_agent")

    assert result.success is True
    assert result.status == "not_running"
    assert result.reason is None
    assert not (artifacts_dir / "waiting.json").exists()
    update_index.assert_called_once_with(artifacts_dir)

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    assert isolated_dismissed_index.exists()
    assert (AgentType.RUNNING, "feature_x", "20260510140000") in (
        load_dismissed_agents()
    )
    assert notifications_by_id()["stale-question"].dismissed is True


def test_kill_named_agent_uses_live_meta_pid_for_waiting_home_agent(
    tmp_path: Path,
) -> None:
    artifacts_dir = setup_waiting_agent(
        tmp_path,
        project_name="home",
        timestamp="20260510150000",
        name="home_waiting",
        pid=33333,
        cl_name="home_feature",
    )
    found = NamedAgent(
        name="home_waiting",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch("sase.agent.running.is_process_alive", return_value=True),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=successful_user_kill(),
        ) as request_kill,
        patch(
            "sase.agent.running.update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        result = kill_named_agent("home_waiting")

    assert result.success is True
    assert result.pid == 33333
    request_kill.assert_called_once_with(
        33333,
        artifacts_dir=artifacts_dir,
        source="agents_kill",
        wait=True,
    )
    assert not (artifacts_dir / "waiting.json").exists()
    update_index.assert_called_once_with(artifacts_dir)

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    assert (
        AgentType.RUNNING,
        "home_feature",
        "20260510150000",
    ) in load_dismissed_agents()


def test_kill_named_agent_uses_live_meta_pid_for_waiting_nonhome_agent(
    tmp_path: Path,
) -> None:
    artifacts_dir = setup_waiting_agent(
        tmp_path,
        project_name="myproj",
        timestamp="20260510160000",
        name="my_waiting",
        pid=44444,
        cl_name="feature_wait",
    )
    found = NamedAgent(
        name="my_waiting",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch("sase.agent.running.is_process_alive", return_value=True),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=successful_user_kill(),
        ) as request_kill,
        patch(
            "sase.agent.running.update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        result = kill_named_agent("my_waiting")

    assert result.success is True
    assert result.pid == 44444
    request_kill.assert_called_once_with(
        44444,
        artifacts_dir=artifacts_dir,
        source="agents_kill",
        wait=True,
    )
    assert not (artifacts_dir / "waiting.json").exists()
    update_index.assert_called_once_with(artifacts_dir)

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    assert (
        AgentType.RUNNING,
        "feature_wait",
        "20260510160000",
    ) in load_dismissed_agents()


def test_kill_named_agent_dead_meta_pid_cleans_up_stale_waiting_agent(
    tmp_path: Path,
) -> None:
    artifacts_dir = setup_waiting_agent(
        tmp_path,
        project_name="home",
        timestamp="20260510170000",
        name="stale_waiting",
        pid=55555,
        cl_name="stale_feature",
    )
    found = NamedAgent(
        name="stale_waiting",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch("sase.agent.running.is_process_alive", return_value=False),
        patch("sase.agent.running.request_user_kill") as request_kill,
        patch(
            "sase.agent.running.update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        result = kill_named_agent("stale_waiting")

    assert result.success is True
    assert result.status == "not_running"
    assert result.changed is True
    request_kill.assert_not_called()
    assert not (artifacts_dir / "waiting.json").exists()
    update_index.assert_called_once_with(artifacts_dir)


def test_kill_named_agent_meta_pid_recycling_guard_does_not_signal(
    tmp_path: Path,
) -> None:
    process = subprocess.Popen(["sleep", "60"])
    try:
        artifacts_dir = setup_waiting_agent(
            tmp_path,
            project_name="home",
            timestamp="20260510180000",
            name="recycled_pid",
            pid=process.pid,
            cl_name="recycled_feature",
        )
        found = NamedAgent(
            name="recycled_pid",
            artifacts_dir=str(artifacts_dir),
            is_done=False,
            outcome=None,
        )

        with (
            patch_home(tmp_path),
            patch("sase.agent.running.find_named_agent", return_value=found),
            patch("sase.agent.running.request_user_kill") as request_kill,
        ):
            result = kill_named_agent("recycled_pid")

        assert result.success is True
        assert result.status == "not_running"
        request_kill.assert_not_called()
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)
