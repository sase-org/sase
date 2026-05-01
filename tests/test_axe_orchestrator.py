"""Tests for the Orchestrator class."""

import signal
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.config import AxeConfig, LumberjackConfig
from sase.axe.orchestrator import (
    Orchestrator,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch AXE_STATE_DIR and ORCHESTRATOR_PID_FILE to use a temp directory."""
    state_dir = tmp_path / ".sase" / "axe"
    state_dir.mkdir(parents=True, exist_ok=True)
    pid_file = state_dir / "orchestrator.pid"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.orchestrator.AXE_STATE_DIR", state_dir),
        patch("sase.axe.orchestrator.ORCHESTRATOR_PID_FILE", pid_file),
    ):
        yield state_dir


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=7200,
        query="",
        lumberjacks={
            "hooks": LumberjackConfig(name="hooks", interval=1, chops=["hook_checks"]),
            "checks": LumberjackConfig(
                name="checks", interval=300, chops=["cl_submitted_checks"]
            ),
        },
    )


# --- Subprocess Spawning Tests ---


@patch(
    "sase.axe.orchestrator.Orchestrator._find_sase_executable",
    return_value="/usr/bin/sase",
)
@patch("subprocess.Popen")
def test_spawn_lumberjack_calls_popen(
    mock_popen: MagicMock,
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that _spawn_lumberjack calls subprocess.Popen with correct args."""
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_popen.return_value = mock_proc

    orch = Orchestrator(axe_config)
    proc = orch._spawn_lumberjack("hooks")

    assert proc.pid == 12345
    # Check that the command includes 'sase axe lumberjack run hooks'
    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert "sase" in cmd[0]
    assert cmd[1:5] == ["axe", "lumberjack", "run", "hooks"]


# --- PID File Tests ---


def test_remove_pid_deletes_file(temp_state_dir: Path, axe_config: AxeConfig) -> None:
    """Test that _remove_pid removes the orchestrator PID file."""
    orch = Orchestrator(axe_config)
    orch._write_pid()
    pid_file = temp_state_dir / "orchestrator.pid"
    assert pid_file.exists()

    orch._remove_pid()
    assert not pid_file.exists()


def test_remove_pid_no_file(temp_state_dir: Path, axe_config: AxeConfig) -> None:
    """Test that _remove_pid doesn't error when file doesn't exist."""
    orch = Orchestrator(axe_config)
    orch._remove_pid()  # Should not raise


# --- SIGTERM Forwarding Tests ---


# --- Existing Orchestrator / Lock Tests ---


def test_cleanup_stale_no_pid_file(temp_state_dir: Path, axe_config: AxeConfig) -> None:
    """No-op when there is no PID file."""
    orch = Orchestrator(axe_config)
    assert orch._cleanup_stale_orchestrator_pid() is None


@patch("os.kill")
def test_cleanup_stale_dead_process(
    mock_kill: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Removes a PID file that points to a dead process."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("99999")
    mock_kill.side_effect = ProcessLookupError

    orch = Orchestrator(axe_config)
    assert orch._cleanup_stale_orchestrator_pid() is None

    # Should have probed with signal 0
    mock_kill.assert_called_once_with(99999, 0)
    assert not pid_file.exists()


@patch("os.kill")
def test_cleanup_stale_live_process_does_not_kill(
    mock_kill: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """A start command treats a live existing orchestrator as success."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("12345")

    mock_kill.return_value = None

    orch = Orchestrator(axe_config)
    assert orch._cleanup_stale_orchestrator_pid() == 12345

    mock_kill.assert_called_once_with(12345, 0)
    assert pid_file.read_text() == "12345"


@patch("os.kill")
def test_cleanup_stale_skips_own_pid(
    mock_kill: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Keeps the PID file when it contains our own PID."""
    import os

    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text(str(os.getpid()))

    orch = Orchestrator(axe_config)
    assert orch._cleanup_stale_orchestrator_pid() == os.getpid()

    mock_kill.assert_not_called()


@patch("sase.axe.orchestrator.acquire_axe_lifetime_lock", return_value=None)
def test_run_exits_without_spawning_when_lifetime_lock_is_held(
    mock_acquire: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Duplicate direct starts exit successfully without supervising children."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("12345")

    orch = Orchestrator(axe_config)
    with patch.object(orch, "_spawn_lumberjack") as mock_spawn:
        assert orch.run() is True

    mock_acquire.assert_called_once()
    mock_spawn.assert_not_called()
    assert pid_file.read_text() == "12345"
    assert "already running (pid 12345)" in capsys.readouterr().out


def test_run_writes_pid_and_releases_lifetime_lock(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """The orchestrator owns the lock for its run and releases it on exit."""
    axe_config.lumberjacks = {}
    orch = Orchestrator(axe_config)

    def interrupt_sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    with (
        patch("sase.axe.orchestrator.init_telemetry"),
        patch("sase.axe.orchestrator.time.sleep", side_effect=interrupt_sleep),
    ):
        assert orch.run() is True

    assert not (temp_state_dir / "orchestrator.pid").exists()
    from sase.axe.lock import AxeLifecycleLock

    lock = AxeLifecycleLock.acquire(blocking=False)
    assert lock is not None
    lock.release()


# --- SIGTERM Forwarding Tests ---


@patch("os.kill")
def test_handle_shutdown_forwards_sigterm(
    mock_kill: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that _handle_shutdown forwards SIGTERM to all children."""
    orch = Orchestrator(axe_config)
    mock_proc1 = MagicMock()
    mock_proc1.pid = 100
    mock_proc1.poll.return_value = None  # Running
    mock_proc2 = MagicMock()
    mock_proc2.pid = 200
    mock_proc2.poll.return_value = None  # Running

    orch._children = {"hooks": mock_proc1, "checks": mock_proc2}
    orch._handle_shutdown(signal.SIGTERM, None)

    assert orch._running is False
    # Should have called os.kill on both children
    calls = mock_kill.call_args_list
    pids_killed = {c[0][0] for c in calls}
    assert pids_killed == {100, 200}
    for c in calls:
        assert c[0][1] == signal.SIGTERM


@patch("os.killpg")
@patch("os.kill")
def test_terminate_children_does_not_signal_process_groups(
    mock_kill: MagicMock,
    mock_killpg: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Axe shutdown targets lumberjack PIDs, not descendant process groups."""
    orch = Orchestrator(axe_config)
    mock_proc = MagicMock()
    mock_proc.pid = 100
    mock_proc.poll.return_value = None
    orch._children = {"hooks": mock_proc}

    orch._terminate_children()

    mock_kill.assert_called_once_with(100, signal.SIGTERM)
    mock_killpg.assert_not_called()
