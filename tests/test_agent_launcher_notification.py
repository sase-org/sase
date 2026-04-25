"""Integration tests for agent-launch notifications emitted by spawn_agent_subprocess."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.notifications.store import load_notifications


@pytest.fixture()
def temp_notifications_dir(tmp_path: Path) -> Iterator[Path]:
    notifications_dir = str(tmp_path / "notifications")
    notifications_file = str(tmp_path / "notifications" / "notifications.jsonl")
    with (
        patch("sase.notifications.store.NOTIFICATIONS_DIR", notifications_dir),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", notifications_file),
    ):
        yield tmp_path


def _spawn(workspace_dir: str, **overrides: object) -> object:
    """Invoke spawn_agent_subprocess with sensible defaults for tests."""
    from sase.agent.launcher import spawn_agent_subprocess

    kwargs: dict[str, object] = {
        "cl_name": "test-cl",
        "project_file": "/tmp/project.gp",
        "workspace_dir": workspace_dir,
        "workspace_num": 1,
        "workflow_name": "ace(run)-20260425",
        "prompt": "%n:my-agent fix the bug",
        "timestamp": "20260425T120000",
        "project_name": "sase",
    }
    kwargs.update(overrides)
    return spawn_agent_subprocess(**kwargs)  # type: ignore[arg-type]


@pytest.fixture()
def patched_spawn(tmp_path: Path) -> Iterator[MagicMock]:
    """Patch subprocess + workspace claim so spawn_agent_subprocess runs offline."""
    proc = MagicMock()
    proc.pid = 4242
    with (
        patch("sase.agent.launcher.subprocess.Popen", return_value=proc) as popen,
        patch("sase.running_field.claim_workspace", return_value=True),
        patch("sase.running_field.transfer_workspace_claim", return_value=True),
    ):
        yield popen


class TestSpawnAgentSubprocessNotifies:
    def test_emits_one_launch_notification_per_call(
        self, temp_notifications_dir: Path, patched_spawn: MagicMock, tmp_path: Path
    ) -> None:
        del patched_spawn
        _spawn(str(tmp_path))
        loaded = load_notifications()
        assert len(loaded) == 1
        n = loaded[0]
        assert n.sender == "agent-launch"
        assert n.action_data["cl_name"] == "test-cl"
        assert n.action_data["agent_name"] == "my-agent"
        assert n.action_data["pid"] == "4242"
        assert n.action_data["workspace_num"] == "1"

    def test_no_notification_on_claim_failure(
        self, temp_notifications_dir: Path, tmp_path: Path
    ) -> None:
        proc = MagicMock()
        proc.pid = 4242
        proc.wait = MagicMock()
        with (
            patch("sase.agent.launcher.subprocess.Popen", return_value=proc),
            patch("sase.running_field.claim_workspace", return_value=False),
        ):
            with pytest.raises(RuntimeError, match="Failed to claim workspace"):
                _spawn(str(tmp_path))

        assert load_notifications() == []

    def test_retry_spawn_records_attempt(
        self, temp_notifications_dir: Path, patched_spawn: MagicMock, tmp_path: Path
    ) -> None:
        del patched_spawn
        _spawn(
            str(tmp_path),
            extra_env={
                "SASE_AGENT_RETRY_ATTEMPT": "2",
                "SASE_AGENT_RETRY_OF_TIMESTAMP": "20260425T100000",
            },
            retry_transfer_from_pid=999,
        )
        n = load_notifications()[0]
        assert n.action_data["retry_attempt"] == "2"
        assert n.action_data["retry_of_timestamp"] == "20260425T100000"

    def test_home_mode_still_notifies(
        self, temp_notifications_dir: Path, patched_spawn: MagicMock, tmp_path: Path
    ) -> None:
        del patched_spawn
        _spawn(str(tmp_path), is_home_mode=True)
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].sender == "agent-launch"
