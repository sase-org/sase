"""Tests for Lumberjack agent-chop dedup, registry, and chop-env behavior."""

import os
import time
from collections.abc import Iterator
from pathlib import Path
from threading import Event, Lock
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

    with patch("sase.axe.lumberjack.is_process_running", return_value=True):
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
        patch("sase.axe.lumberjack.is_process_running", return_value=False),
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
def test_agent_chop_reaps_exited_in_memory_child_pid(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """An exited direct child PID is reaped and does not block relaunch."""
    config = LumberjackConfig(
        name="dedup_reap",
        interval=10,
        chops=[ChopConfig(name="my_agent", description="", agent="some_agent")],
    )
    lumberjack = Lumberjack("dedup_reap", config, axe_config)
    lumberjack._agent_pids["my_agent"] = {12345}

    with (
        patch("os.waitpid", return_value=(12345, 0)) as mock_waitpid,
        patch("sase.axe.lumberjack.is_process_running") as mock_is_running,
    ):
        assert lumberjack._is_agent_eligible(config.chops[0]) is True

    mock_waitpid.assert_called_once_with(12345, os.WNOHANG)
    mock_is_running.assert_not_called()
    assert "my_agent" not in lumberjack._agent_pids


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_agent_chop_stale_in_memory_pid_does_not_block_when_not_reaped(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """A stale non-child or zombie-like PID is pruned by the liveness check."""
    config = LumberjackConfig(
        name="dedup_stale_memory",
        interval=10,
        chops=[ChopConfig(name="my_agent", description="", agent="some_agent")],
    )
    lumberjack = Lumberjack("dedup_stale_memory", config, axe_config)
    lumberjack._agent_pids["my_agent"] = {99999}

    with (
        patch("os.waitpid", side_effect=ChildProcessError()),
        patch("sase.axe.lumberjack.is_process_running", return_value=False),
    ):
        assert lumberjack._is_agent_eligible(config.chops[0]) is True

    assert "my_agent" not in lumberjack._agent_pids


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
def test_run_tick_launches_agent_chops_sequentially_in_config_order(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Same-tick agent chops launch one at a time, in configured order."""
    config = LumberjackConfig(
        name="sequential_agents",
        interval=10,
        chops=[
            ChopConfig(
                name="first_agent",
                description="",
                agent="first prompt",
                run_every=3600,
            ),
            ChopConfig(
                name="second_agent",
                description="",
                agent="second prompt",
                run_every=3600,
            ),
        ],
    )
    lumberjack = Lumberjack("sequential_agents", config, axe_config)

    lock = Lock()
    active_launches = 0
    max_active_launches = 0
    claimed_workspaces: set[int] = set()
    launch_order: list[str] = []
    claims_seen_by_launch: list[tuple[str, tuple[int, ...]]] = []

    def launch_agent(
        query: str,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> AgentLaunchResult:
        nonlocal active_launches, max_active_launches
        assert extra_env is not None
        chop_name = extra_env["SASE_CHOP_NAME"]
        with lock:
            launch_order.append(chop_name)
            claims_seen_by_launch.append((chop_name, tuple(sorted(claimed_workspaces))))
            active_launches += 1
            max_active_launches = max(max_active_launches, active_launches)

        try:
            if chop_name == "first_agent":
                time.sleep(0.05)
                with lock:
                    claimed_workspaces.add(100)
                workspace_num = 100
                pid = 111
            else:
                with lock:
                    saw_first_claim = 100 in claimed_workspaces
                if not saw_first_claim:
                    raise AssertionError("second launch raced before first claim")
                workspace_num = 101
                pid = 222

            return AgentLaunchResult(
                pid=pid,
                workspace_num=workspace_num,
                workspace_dir=f"/tmp/ws{workspace_num}",
                output_path=f"/tmp/out{workspace_num}",
                project_file="/tmp/projects/proj/proj.gp",
                project_name="proj",
                workflow_name=f"ace(run)-260101_1200{pid}",
                cl_name="proj",
                timestamp=f"260101_1200{pid}",
            )
        finally:
            with lock:
                active_launches -= 1

    with patch("sase.agent.launcher.launch_agent_from_cwd", side_effect=launch_agent):
        lumberjack._run_tick()

    assert launch_order == ["first_agent", "second_agent"]
    assert claims_seen_by_launch == [
        ("first_agent", ()),
        ("second_agent", (100,)),
    ]
    assert max_active_launches == 1
    assert lumberjack._metrics.errors_encountered == 0
    assert lumberjack._metrics.chops_executed == 2
    assert set(lumberjack._chop_timestamps) == {"first_agent", "second_agent"}


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_launches_agent_chop_while_script_chop_is_running(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Script chops stay concurrent and do not block eligible agent launches."""
    config = LumberjackConfig(
        name="mixed_chops",
        interval=10,
        chops=[
            ChopConfig(name="slow_script", description=""),
            ChopConfig(
                name="agent_chop",
                description="",
                agent="agent prompt",
                run_every=3600,
            ),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    script_started = Event()
    agent_launched = Event()

    def run_script(*args: object, **kwargs: object) -> object:
        script_started.set()
        assert agent_launched.wait(timeout=1.0), "agent launch waited for script"
        return ok_result()

    def launch_agent(
        query: str,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> AgentLaunchResult:
        assert script_started.wait(timeout=1.0), "script chop did not start"
        assert extra_env is not None
        assert extra_env["SASE_CHOP_NAME"] == "agent_chop"
        agent_launched.set()
        return AgentLaunchResult(
            pid=333,
            workspace_num=100,
            workspace_dir="/tmp/ws100",
            output_path="/tmp/out100",
            project_file="/tmp/projects/proj/proj.gp",
            project_name="proj",
            workflow_name="ace(run)-260101_1200333",
            cl_name="proj",
            timestamp="260101_1200333",
        )

    mock_run.side_effect = run_script
    lumberjack = Lumberjack("mixed_chops", config, axe_config)
    with patch("sase.agent.launcher.launch_agent_from_cwd", side_effect=launch_agent):
        lumberjack._run_tick()

    assert mock_run.call_count == 1
    assert agent_launched.is_set()
    assert lumberjack._metrics.errors_encountered == 0
    assert lumberjack._metrics.chops_executed == 2
    assert set(lumberjack._chop_timestamps) == {"agent_chop"}


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


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_agent_chop_completed_outer_pid_does_not_block_without_live_registry_record(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """A completed outer workflow PID cannot block solely via memory fallback."""
    from sase.axe.chop_agents import _record_chop_agent_launch

    config = LumberjackConfig(
        name="dedup_completed_outer",
        interval=10,
        chops=[ChopConfig(name="my_agent", description="", agent="some_agent")],
    )
    _record_chop_agent_launch(
        lumberjack_name="dedup_completed_outer",
        chop_name="my_agent",
        run_id="outer-run",
        pid=99999,
        project_file="/tmp/projects/proj/proj.gp",
        project_name="proj",
        workspace_num=1,
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
        prompt="some_agent",
    )

    lumberjack = Lumberjack("dedup_completed_outer", config, axe_config)
    lumberjack._agent_pids["my_agent"] = {99999}
    with (
        patch("sase.axe.chop_agents.is_process_running", return_value=False),
        patch("sase.axe.lumberjack.is_process_running", return_value=False),
    ):
        assert lumberjack._is_agent_eligible(config.chops[0]) is True


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_agent_chop_live_durable_child_record_blocks_relaunch(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """A live child spawned under chop env still dedups the parent chop."""
    from sase.axe.chop_agents import _record_chop_agent_launch, prompt_hash

    config = LumberjackConfig(
        name="dedup_live_child",
        interval=10,
        chops=[
            ChopConfig(
                name="pylimit_split",
                description="",
                agent="#!sase/pylimit_split %approve",
            )
        ],
    )
    _record_chop_agent_launch(
        lumberjack_name="dedup_live_child",
        chop_name="pylimit_split",
        run_id="shared-run",
        pid=88888,
        project_file="/tmp/projects/proj/proj.gp",
        project_name="proj",
        workspace_num=2,
        workflow_name="ace(run)-260101_120100",
        cl_name="proj",
        timestamp="260101_120100",
        prompt="#sase/pysplit:src/sase/large_file.py",
        prompt_hash_value=prompt_hash("#!sase/pylimit_split %approve"),
    )

    lumberjack = Lumberjack("dedup_live_child", config, axe_config)
    with patch("sase.axe.chop_agents.is_process_running", return_value=True):
        assert lumberjack._is_agent_eligible(config.chops[0]) is False


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
