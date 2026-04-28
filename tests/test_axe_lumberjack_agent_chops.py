"""Tests for Lumberjack agent-chop dedup, registry, and chop-env behavior."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launcher import AgentLaunchResult
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack
from tests._axe_lumberjack_fixtures import ok_result


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch AXE_STATE_DIR and JACK_STATE_DIR to use a temp directory."""
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.JACK_STATE_DIR", lumberjack_dir),
    ):
        yield state_dir


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3, max_agent_runners=3, zombie_timeout_seconds=3600, query=""
    )


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_agent_chop_skips_when_already_running(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that a second agent chop launch is skipped when one is already running."""
    config = LumberjackConfig(
        name="dedup",
        interval=10,
        chops=[ChopConfig(name="my_agent", description="", agent="some_agent")],
    )
    lumberjack = Lumberjack("dedup", config, axe_config)

    # Simulate a still-alive PID
    lumberjack._agent_pids["my_agent"] = {99999}

    with patch("os.kill") as mock_kill:
        # os.kill(pid, 0) succeeds → process is alive
        mock_kill.return_value = None
        result = lumberjack._is_agent_eligible(config.chops[0])

    assert result is False


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_agent_chop_launches_after_previous_completes(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that a new agent launches once the previous one has exited."""
    config = LumberjackConfig(
        name="dedup2",
        interval=10,
        chops=[ChopConfig(name="my_agent", description="", agent="some_agent")],
    )
    lumberjack = Lumberjack("dedup2", config, axe_config)

    # Simulate a dead PID
    lumberjack._agent_pids["my_agent"] = {99999}

    mock_proc = MagicMock()
    mock_proc.pid = 12345

    with (
        patch("os.kill", side_effect=OSError("No such process")),
        patch(
            "sase.agent.launcher.launch_agent_from_cwd", return_value=mock_proc
        ) as mock_launch,
    ):
        # Verify eligibility check passes after old process exits
        assert lumberjack._is_agent_eligible(config.chops[0]) is True
        # Launch the agent chop
        result = lumberjack._launch_agent_chop(config.chops[0])

    assert result.success is True
    assert result.agent_pid == 12345
    mock_launch.assert_called_once()
    assert mock_launch.call_args.args == ("some_agent",)
    extra_env = mock_launch.call_args.kwargs["extra_env"]
    assert extra_env["SASE_CHOP_LUMBERJACK"] == "dedup2"
    assert extra_env["SASE_CHOP_NAME"] == "my_agent"
    assert extra_env["SASE_CHOP_RUN_ID"]


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_every_agent_chop_is_not_auto_dismissed(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Recurring agent chops launch visibly: no SASE_AGENT_AUTO_DISMISS env var."""
    config = LumberjackConfig(
        name="recurring",
        interval=10,
        chops=[
            ChopConfig(
                name="my_agent",
                description="",
                agent="some_agent",
                run_every=3600,
            )
        ],
    )
    lumberjack = Lumberjack("recurring", config, axe_config)

    mock_proc = MagicMock()
    mock_proc.pid = 12345

    with patch(
        "sase.agent.launcher.launch_agent_from_cwd", return_value=mock_proc
    ) as mock_launch:
        result = lumberjack._launch_agent_chop(config.chops[0])

    assert result.success is True
    extra_env = mock_launch.call_args.kwargs["extra_env"]
    assert "SASE_AGENT_AUTO_DISMISS" not in extra_env
    # Registry/dedup metadata is still preserved.
    assert extra_env["SASE_CHOP_LUMBERJACK"] == "recurring"
    assert extra_env["SASE_CHOP_NAME"] == "my_agent"
    assert extra_env["SASE_CHOP_RUN_ID"]
    assert extra_env["SASE_CHOP_PROMPT_HASH"]


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_visible_run_every_agent_chop_is_still_deduped_by_registry(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """A visible recurring chop is still deduped by a live registry record."""
    config = LumberjackConfig(
        name="recurring_dedup",
        interval=10,
        chops=[
            ChopConfig(
                name="my_agent",
                description="",
                agent="some_agent",
                run_every=3600,
            )
        ],
    )
    first_lumberjack = Lumberjack("recurring_dedup", config, axe_config)
    launch_result = AgentLaunchResult(
        pid=12345,
        workspace_num=7,
        workspace_dir="/tmp/ws7",
        output_path="/tmp/out",
        project_file="/tmp/projects/proj/proj.gp",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )

    with patch("sase.agent.launcher.launch_agent_from_cwd", return_value=launch_result):
        result = first_lumberjack._launch_agent_chop(config.chops[0])

    assert result.success is True

    restarted_lumberjack = Lumberjack("recurring_dedup", config, axe_config)
    with patch("sase.axe.chop_agents.is_process_running", return_value=True):
        assert restarted_lumberjack._is_agent_eligible(config.chops[0]) is False


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_agent_chop_registry_skips_after_lumberjack_restart(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """A live registry record prevents duplicate launch after restart."""
    config = LumberjackConfig(
        name="dedup_restart",
        interval=10,
        chops=[ChopConfig(name="my_agent", description="", agent="some_agent")],
    )
    first_lumberjack = Lumberjack("dedup_restart", config, axe_config)
    launch_result = AgentLaunchResult(
        pid=12345,
        workspace_num=7,
        workspace_dir="/tmp/ws7",
        output_path="/tmp/out",
        project_file="/tmp/projects/proj/proj.gp",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )

    with patch("sase.agent.launcher.launch_agent_from_cwd", return_value=launch_result):
        result = first_lumberjack._launch_agent_chop(config.chops[0])

    assert result.success is True

    restarted_lumberjack = Lumberjack("dedup_restart", config, axe_config)
    with patch("sase.axe.chop_agents.is_process_running", return_value=True):
        assert restarted_lumberjack._is_agent_eligible(config.chops[0]) is False


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_agent_chop_registry_prunes_dead_pid(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Dead registry records are pruned and do not block relaunch."""
    from sase.axe.chop_agents import _record_chop_agent_launch

    config = LumberjackConfig(
        name="dedup_prune",
        interval=10,
        chops=[ChopConfig(name="my_agent", description="", agent="some_agent")],
    )
    _record_chop_agent_launch(
        lumberjack_name="dedup_prune",
        chop_name="my_agent",
        run_id="old",
        pid=99999,
        project_file="/tmp/projects/proj/proj.gp",
        project_name="proj",
        workspace_num=1,
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
        prompt="some_agent",
    )

    lumberjack = Lumberjack("dedup_prune", config, axe_config)
    with patch("sase.axe.chop_agents.is_process_running", return_value=False):
        assert lumberjack._is_agent_eligible(config.chops[0]) is True


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_script_chop_receives_chop_env(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """External chop scripts receive durable chop identity env vars."""
    config = LumberjackConfig(
        name="scripts",
        interval=10,
        chops=[ChopConfig(name="script_chop", description="", env={"EXTRA": "1"})],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = ok_result()

    lumberjack = Lumberjack("scripts", config, axe_config)
    lumberjack._run_tick()

    env = mock_run.call_args.kwargs["env"]
    assert env["EXTRA"] == "1"
    assert env["SASE_CHOP_LUMBERJACK"] == "scripts"
    assert env["SASE_CHOP_NAME"] == "script_chop"
    assert env["SASE_CHOP_RUN_ID"]
