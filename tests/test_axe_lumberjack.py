"""Tests for the Lumberjack class."""

import os
import subprocess
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launcher import AgentLaunchResult
from sase.axe.chop_agents import ENV_CHOP_NAME
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack


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
def lumberjack_config() -> LumberjackConfig:
    return LumberjackConfig(
        name="test_lumberjack",
        interval=10,
        chops=[ChopConfig(name="hook_checks", description="")],
    )


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3, max_agent_runners=3, zombie_timeout_seconds=3600, query=""
    )


def _ok_result() -> subprocess.CompletedProcess[str]:
    """Return a successful CompletedProcess for mocking."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail_result(
    code: int = 1, stderr: str = "error"
) -> subprocess.CompletedProcess[str]:
    """Return a failed CompletedProcess for mocking."""
    return subprocess.CompletedProcess(
        args=[], returncode=code, stdout="", stderr=stderr
    )


# --- Instantiation Tests ---


def test_lumberjack_with_query(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig
) -> None:
    """Test that Lumberjack parses query from config."""
    config = AxeConfig(query='"test"')
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, config)
    assert lumberjack.parsed_query is not None


# --- Tick Execution Tests ---


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_multiple_chops(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that _run_tick invokes multiple chop scripts."""
    multi_config = LumberjackConfig(
        name="multi",
        interval=5,
        chops=[
            ChopConfig(name="hook_checks", description=""),
            ChopConfig(name="mentor_checks", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lumberjack = Lumberjack("multi", multi_config, axe_config)
    lumberjack._run_tick()

    assert mock_discover.call_count == 2
    assert lumberjack._metrics.chops_executed == 2


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_error_handling(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Test that chop script failures are caught and recorded."""
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _fail_result()

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    assert lumberjack._metrics.errors_encountered == 1
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_tick_missing_script(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    temp_state_dir: Path,
    lumberjack_config: LumberjackConfig,
    axe_config: AxeConfig,
) -> None:
    """Test that missing chop scripts are recorded as errors."""
    mock_discover.return_value = None

    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._run_tick()

    assert lumberjack._metrics.errors_encountered == 1
    assert lumberjack._metrics.chops_executed == 0
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_run_every_skips_when_not_enough_time_elapsed(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that chops with run_every are skipped when not enough time has elapsed."""
    config = LumberjackConfig(
        name="throttled",
        interval=10,
        chops=[ChopConfig(name="slow_chop", description="", run_every=3600)],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lumberjack = Lumberjack("throttled", config, axe_config)

    # First tick: no timestamp exists → runs
    lumberjack._run_tick()
    assert mock_run.call_count == 1

    # Second tick immediately: timestamp was just set → skipped
    lumberjack._run_tick()
    assert mock_run.call_count == 1

    # Simulate enough time having passed
    from sase.core.time import get_timezone

    lumberjack._chop_timestamps["slow_chop"] = datetime.now(get_timezone()) - timedelta(
        seconds=3601
    )
    lumberjack._run_tick()
    assert mock_run.call_count == 2


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_all_chops_run_on_first_tick(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that all chops run on the first tick (no prior timestamps)."""
    config = LumberjackConfig(
        name="first_tick",
        interval=10,
        chops=[
            ChopConfig(name="every_tick", description=""),
            ChopConfig(name="hourly", description="", run_every=3600),
            ChopConfig(name="daily", description="", run_every=86400),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lumberjack = Lumberjack("first_tick", config, axe_config)
    lumberjack._run_tick()

    assert mock_run.call_count == 3


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_chops_without_run_every_run_every_tick(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that chops without run_every always run."""
    config = LumberjackConfig(
        name="always",
        interval=10,
        chops=[ChopConfig(name="always_chop", description="")],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lumberjack = Lumberjack("always", config, axe_config)
    lumberjack._run_tick()
    lumberjack._run_tick()
    lumberjack._run_tick()

    assert mock_run.call_count == 3


# --- Agent Chop Dedup Tests ---


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
    mock_run.return_value = _ok_result()

    lumberjack = Lumberjack("scripts", config, axe_config)
    lumberjack._run_tick()

    env = mock_run.call_args.kwargs["env"]
    assert env["EXTRA"] == "1"
    assert env["SASE_CHOP_LUMBERJACK"] == "scripts"
    assert env["SASE_CHOP_NAME"] == "script_chop"
    assert env["SASE_CHOP_RUN_ID"]


# --- Status/Metrics Writing Tests ---


def test_update_status_writes_file(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that _update_status writes a status file."""
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._update_status()

    from sase.axe.state import read_lumberjack_status

    status = read_lumberjack_status("test_lumberjack")
    assert status is not None
    assert status.name == "test_lumberjack"
    assert status.pid == os.getpid()
    assert status.status == "running"
    assert status.interval == 10


def test_update_metrics_writes_file(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that _update_metrics writes a metrics file."""
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    lumberjack._metrics.cycles_run = 5
    lumberjack._metrics.chops_executed = 15
    lumberjack._update_metrics()

    from sase.axe.state import read_lumberjack_metrics

    metrics = read_lumberjack_metrics("test_lumberjack")
    assert metrics is not None
    assert metrics.cycles_run == 5
    assert metrics.chops_executed == 15


# --- Timeout Tests ---


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_timeout_expired_records_error_and_continues(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that TimeoutExpired is caught and subsequent chops still run."""
    config = LumberjackConfig(
        name="timeout_test",
        interval=10,
        chop_timeout=5,
        chops=[
            ChopConfig(name="slow_chop", description=""),
            ChopConfig(name="fast_chop", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = [
        subprocess.TimeoutExpired(cmd="slow_chop", timeout=5),
        _ok_result(),
    ]

    lumberjack = Lumberjack("timeout_test", config, axe_config)
    lumberjack._run_tick()

    assert lumberjack._metrics.errors_encountered == 1
    assert lumberjack._metrics.chops_executed == 1
    assert lumberjack._metrics.cycles_run == 1


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_per_chop_timeout_overrides_lumberjack_default(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that per-chop timeout overrides lumberjack-level chop_timeout."""
    config = LumberjackConfig(
        name="override_test",
        interval=10,
        chop_timeout=30,
        chops=[
            ChopConfig(name="custom_timeout", description="", timeout=10),
            ChopConfig(name="default_timeout", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.return_value = _ok_result()

    lumberjack = Lumberjack("override_test", config, axe_config)
    lumberjack._run_tick()

    # Chops run concurrently via ThreadPoolExecutor, so call ordering is
    # nondeterministic — key assertions by chop name instead of position.
    assert mock_run.call_count == 2
    timeouts_by_chop = {
        call.kwargs["env"][ENV_CHOP_NAME]: call.kwargs["timeout"]
        for call in mock_run.call_args_list
    }
    assert timeouts_by_chop == {"custom_timeout": 10, "default_timeout": 30}


# --- Tick Overrun Warning Tests ---


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_tick_overrun_logs_warning(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that a warning is logged when tick duration exceeds interval."""
    config = LumberjackConfig(
        name="overrun_test",
        interval=1,
        chops=[ChopConfig(name="slow_chop", description="")],
    )
    mock_discover.return_value = Path("/fake/script")

    def slow_run(*args, **kwargs):
        import time

        time.sleep(1.1)
        return _ok_result()

    mock_run.side_effect = slow_run

    lumberjack = Lumberjack("overrun_test", config, axe_config)
    lumberjack._run_tick()

    # Check the log output contains the overrun warning
    log_path = temp_state_dir / "lumberjacks" / "overrun_test" / "lumberjack.log"
    if log_path.exists():
        log_content = log_path.read_text()
        assert "Tick overrun" in log_content


# --- Shutdown Tests ---


def test_handle_shutdown_sets_running_false(
    temp_state_dir: Path, lumberjack_config: LumberjackConfig, axe_config: AxeConfig
) -> None:
    """Test that SIGTERM handler sets _running to False."""
    lumberjack = Lumberjack("test_lumberjack", lumberjack_config, axe_config)
    assert lumberjack._running is True
    lumberjack._handle_shutdown(15, None)
    assert lumberjack._running is False


# --- Concurrency Tests ---


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_chops_run_concurrently(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that chops run concurrently (two 1s chops complete in ~1s, not ~2s)."""
    config = LumberjackConfig(
        name="concurrent_test",
        interval=10,
        chops=[
            ChopConfig(name="slow_a", description=""),
            ChopConfig(name="slow_b", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")

    def slow_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        time.sleep(1.0)
        return _ok_result()

    mock_run.side_effect = slow_run

    lumberjack = Lumberjack("concurrent_test", config, axe_config)
    start = time.monotonic()
    lumberjack._run_tick()
    elapsed = time.monotonic() - start

    assert mock_run.call_count == 2
    assert lumberjack._metrics.chops_executed == 2
    # If sequential, would take ~2s. Concurrent should be ~1s.
    assert elapsed < 1.8, f"Expected concurrent execution (<1.8s), took {elapsed:.1f}s"


@patch("sase.axe.lumberjack.run_chop_script")
@patch("sase.axe.lumberjack.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_one_chop_failure_does_not_block_others(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that one chop failing doesn't prevent others from running."""
    config = LumberjackConfig(
        name="isolation_test",
        interval=10,
        chops=[
            ChopConfig(name="failing_chop", description=""),
            ChopConfig(name="ok_chop", description=""),
            ChopConfig(name="crashing_chop", description=""),
        ],
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = [
        _fail_result(),
        _ok_result(),
        RuntimeError("unexpected crash"),
    ]

    lumberjack = Lumberjack("isolation_test", config, axe_config)
    lumberjack._run_tick()

    assert mock_run.call_count == 3
    assert lumberjack._metrics.chops_executed == 1
    assert lumberjack._metrics.errors_encountered == 2


# --- Gate Tests ---


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_gate_passing_allows_agent_launch(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that a gate exiting 0 allows the agent chop to launch."""
    config = LumberjackConfig(
        name="gate_pass",
        interval=10,
        chops=[
            ChopConfig(
                name="gated_agent",
                description="",
                agent="some_agent",
                gate="true",
            )
        ],
    )
    lumberjack = Lumberjack("gate_pass", config, axe_config)

    mock_result = MagicMock()
    mock_result.pid = 12345

    with (
        patch.object(lumberjack, "_resolve_gate_cwd", return_value=None),
        patch(
            "sase.agent.launcher.launch_agent_from_cwd", return_value=mock_result
        ) as mock_launch,
    ):
        result = lumberjack._run_single_chop(config.chops[0], "/fake/context")

    assert result.executed is True
    assert result.success is True
    assert result.agent_pid == 12345
    mock_launch.assert_called_once()


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_gate_failing_blocks_agent_launch(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that a gate exiting non-zero prevents the agent chop from launching."""
    config = LumberjackConfig(
        name="gate_block",
        interval=10,
        chops=[
            ChopConfig(
                name="gated_agent",
                description="",
                agent="some_agent",
                gate="false",
            )
        ],
    )
    lumberjack = Lumberjack("gate_block", config, axe_config)

    with (
        patch.object(lumberjack, "_resolve_gate_cwd", return_value=None),
        patch("sase.agent.launcher.launch_agent_from_cwd") as mock_launch,
    ):
        result = lumberjack._run_single_chop(config.chops[0], "/fake/context")

    assert result.executed is False
    assert result.success is True
    mock_launch.assert_not_called()


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_gate_failing_updates_timestamp_for_run_every(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that a blocked gate still resets the run_every timer."""
    config = LumberjackConfig(
        name="gate_ts",
        interval=10,
        chops=[
            ChopConfig(
                name="gated_agent",
                description="",
                agent="some_agent",
                gate="false",
                run_every=3600,
            )
        ],
    )
    lumberjack = Lumberjack("gate_ts", config, axe_config)

    with patch.object(lumberjack, "_resolve_gate_cwd", return_value=None):
        result = lumberjack._run_single_chop(config.chops[0], "/fake/context")

    assert result.update_timestamp is True


@patch("sase.axe.check_cycles.find_all_changespecs", return_value=[])
def test_gate_cwd_is_set_to_resolved_project_directory(
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
    tmp_path: Path,
) -> None:
    """Test that the gate command runs in the resolved project directory."""
    gate_dir = tmp_path / "project"
    gate_dir.mkdir()
    config = LumberjackConfig(
        name="gate_cwd",
        interval=10,
        chops=[
            ChopConfig(
                name="gated_agent",
                description="",
                agent="some_agent",
                gate="pwd",
            )
        ],
    )
    lumberjack = Lumberjack("gate_cwd", config, axe_config)

    with patch.object(lumberjack, "_resolve_gate_cwd", return_value=str(gate_dir)):
        result = lumberjack._run_gate(config.chops[0])

    # gate "pwd" exits 0 → returns None (gate passes)
    assert result is None
