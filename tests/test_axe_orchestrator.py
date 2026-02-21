"""Tests for the Orchestrator class."""

import os
import signal
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.config import AxeConfig, LumberjackConfig
from sase.axe.orchestrator import (
    ORCHESTRATOR_PID_FILE,
    Orchestrator,
    read_orchestrator_pid,
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
        max_runners=5,
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


@patch(
    "sase.axe.orchestrator.Orchestrator._find_sase_executable",
    return_value="/usr/bin/sase",
)
@patch("subprocess.Popen")
def test_orchestrator_spawns_all_lumberjacks(
    mock_popen: MagicMock,
    mock_find: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Test that the orchestrator spawns one subprocess per lumberjack."""
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None  # Still running
    mock_popen.return_value = mock_proc

    orch = Orchestrator(axe_config)

    # Simulate: spawn all then stop immediately
    orch._running = True
    for name in axe_config.lumberjacks:
        orch._children[name] = orch._spawn_lumberjack(name)

    assert len(orch._children) == 2
    assert set(orch._children.keys()) == {"hooks", "checks"}


# --- PID File Tests ---


def test_write_pid_creates_file(temp_state_dir: Path, axe_config: AxeConfig) -> None:
    """Test that _write_pid creates the orchestrator PID file."""
    orch = Orchestrator(axe_config)
    orch._write_pid()

    pid_file = temp_state_dir / "orchestrator.pid"
    assert pid_file.exists()
    assert int(pid_file.read_text().strip()) == os.getpid()


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


# --- read_orchestrator_pid Tests ---


def test_read_orchestrator_pid_no_file(temp_state_dir: Path) -> None:
    """Test that read_orchestrator_pid returns None when no PID file."""
    pid_file = temp_state_dir / "orchestrator.pid"
    with patch("sase.axe.orchestrator.ORCHESTRATOR_PID_FILE", pid_file):
        assert read_orchestrator_pid() is None


@patch("sase.axe.orchestrator.is_process_running", return_value=True)
def test_read_orchestrator_pid_running(
    mock_running: MagicMock, temp_state_dir: Path
) -> None:
    """Test that read_orchestrator_pid returns PID when process is running."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("42")
    with patch("sase.axe.orchestrator.ORCHESTRATOR_PID_FILE", pid_file):
        assert read_orchestrator_pid() == 42


@patch("sase.axe.orchestrator.is_process_running", return_value=False)
def test_read_orchestrator_pid_stale(
    mock_running: MagicMock, temp_state_dir: Path
) -> None:
    """Test that stale PID file is cleaned up."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("99999")
    with patch("sase.axe.orchestrator.ORCHESTRATOR_PID_FILE", pid_file):
        assert read_orchestrator_pid() is None
        assert not pid_file.exists()
