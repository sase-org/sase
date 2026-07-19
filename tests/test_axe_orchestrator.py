"""Tests for the Orchestrator class."""

import io
import os
import signal
import subprocess
import threading
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
    mock_proc.stdout = None
    mock_popen.return_value = mock_proc

    orch = Orchestrator(axe_config)
    proc = orch._spawn_lumberjack("hooks")

    assert proc.pid == 12345
    # Check that the command includes 'sase axe lumberjack run hooks'
    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert "sase" in cmd[0]
    assert cmd[1:5] == ["axe", "lumberjack", "run", "hooks"]
    assert call_args.kwargs["stdout"] == subprocess.PIPE
    assert call_args.kwargs["stderr"] == subprocess.STDOUT


def test_stream_child_output_caps_legacy_log(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Orchestrator child stdout logs are bounded."""
    axe_config.lumberjack_log_max_bytes = 128
    orch = Orchestrator(axe_config)
    stream = io.BytesIO(b"old\n" * 100 + b"newest\n")

    orch._stream_child_output("hooks", stream)

    log_file = temp_state_dir / "logs" / "lumberjack-hooks.log"
    data = log_file.read_bytes()
    assert len(data) <= 128
    assert b"newest\n" in data


def test_stream_child_output_flushes_available_pipe_bytes(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """A partial pipe chunk is logged without waiting for EOF or 64 KiB."""
    orch = Orchestrator(axe_config)
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb", buffering=64 * 1024)
    appended = threading.Event()
    chunks: list[bytes] = []

    def capture_append(
        _path: Path,
        data: bytes,
        *,
        max_bytes: int,
        temp_max_age_seconds: int,
    ) -> None:
        del max_bytes, temp_max_age_seconds
        chunks.append(data)
        appended.set()

    with patch(
        "sase.axe.orchestrator.append_bounded_log",
        side_effect=capture_append,
    ):
        thread = threading.Thread(
            target=orch._stream_child_output,
            args=("hooks", stream),
        )
        thread.start()
        os.write(write_fd, b"startup ready\n")
        flushed_before_eof = appended.wait(timeout=1)
        os.close(write_fd)
        thread.join(timeout=1)

    assert flushed_before_eof
    assert not thread.is_alive()
    assert chunks == [b"startup ready\n"]


# --- Crash-loop Restart Tests ---


def test_lumberjack_restart_uses_capped_exponential_backoff(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    axe_config.lumberjack_restart_backoff_max_seconds = 4
    orch = Orchestrator(axe_config)
    proc = MagicMock()
    proc.poll.return_value = 1
    orch._record_lumberjack_started("hooks", proc, now=0)

    orch._poll_lumberjack("hooks", now=0)
    state = orch._restart_state("hooks")
    assert state.restart_at == 1

    restarted = MagicMock()
    restarted.poll.return_value = 1
    with patch.object(orch, "_spawn_lumberjack", return_value=restarted) as spawn:
        orch._poll_lumberjack("hooks", now=0.9)
        spawn.assert_not_called()
        orch._poll_lumberjack("hooks", now=1)
        spawn.assert_called_once_with("hooks")

    orch._poll_lumberjack("hooks", now=1.1)
    assert state.restart_at == pytest.approx(3.1)
    assert state.backoff_seconds == 2

    orch._schedule_lumberjack_restart("hooks", now=4, exit_code=1)
    assert state.backoff_seconds == 4
    orch._schedule_lumberjack_restart("hooks", now=9, exit_code=1)
    assert state.backoff_seconds == 4


def test_lumberjack_restart_backoff_resets_after_healthy_run(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    orch = Orchestrator(axe_config)
    state = orch._restart_state("hooks")
    state.backoff_seconds = 60
    state.consecutive_failures = 8
    state.recent_failures.extend([1, 2, 3])
    state.alert_sent = True

    proc = MagicMock()
    proc.poll.return_value = 7
    orch._record_lumberjack_started("hooks", proc, now=0)
    orch._poll_lumberjack("hooks", now=301)

    assert state.backoff_seconds == 1
    assert state.restart_at == 302
    assert state.consecutive_failures == 1
    assert list(state.recent_failures) == [301]
    assert state.alert_sent is False


def test_crash_loop_writes_error_and_notification_once(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    log_file = temp_state_dir / "logs" / "lumberjack-hooks.log"
    log_file.parent.mkdir(parents=True)
    log_file.write_text("startup\nboom traceback\n")
    orch = Orchestrator(axe_config)

    with (
        patch("sase.axe.orchestrator.append_error") as append_error,
        patch(
            "sase.notifications.senders.notify_workflow_complete"
        ) as notify_workflow_complete,
    ):
        for now in (0.0, 10.0, 20.0, 30.0):
            orch._schedule_lumberjack_restart(
                "hooks",
                now=now,
                exit_code=17,
            )

    append_error.assert_called_once()
    error = append_error.call_args.args[0]
    assert error["lumberjack"] == "hooks"
    assert "3 failures within 60s" in error["error"]
    assert "exit code 17" in error["error"]
    assert "boom traceback" in error["traceback"]

    notify_workflow_complete.assert_called_once()
    notification = notify_workflow_complete.call_args.kwargs
    assert notification["sender"] == "axe"
    assert "Lumberjack 'hooks'" in notification["notes"][0]
    assert "exit code 17" in notification["notes"][0]
    assert "boom traceback" in notification["notes"][1]
    assert "extra_files" not in notification
    assert notification["tags"] == ["axe", "crash-loop"]


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


def test_write_pid_atomically_replaces_complete_file(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """The published PID is always an intact old or new integer."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("12345\n")
    real_replace = os.replace

    def assert_complete_then_replace(source: Path, destination: Path) -> None:
        assert int(Path(source).read_text().strip()) == os.getpid()
        assert int(pid_file.read_text().strip()) == 12345
        real_replace(source, destination)

    orch = Orchestrator(axe_config)
    with patch(
        "sase.axe.orchestrator.os.replace",
        side_effect=assert_complete_then_replace,
    ):
        orch._write_pid()

    assert int(pid_file.read_text().strip()) == os.getpid()


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
        patch("sase.axe.orchestrator.reap_stale_log_rotation_temps") as mock_reap,
        patch("sase.axe.orchestrator.time.sleep", side_effect=interrupt_sleep),
    ):
        assert orch.run() is True

    mock_reap.assert_called_once_with(
        temp_state_dir,
        max_age_seconds=axe_config.lumberjack_log_temp_max_age_seconds,
    )
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
