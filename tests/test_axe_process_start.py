"""Tests for starting and restarting the axe process."""

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.config import AxeConfig
from sase.axe.desired_state import read_desired_state
from sase.axe.ensure import ensure_axe
from sase.axe.lock import AxeLifecycleLock
from sase.axe._process_start import (
    _build_axe_start_command,
    _compose_axe_daemon_env,
    _wait_for_daemon_start,
)
from sase.axe._process_types import AxeOrchestratorProbe
from sase.axe.systemd_scope import (
    AXE_SYSTEMD_SCOPE_DISABLE_ENV,
    wrap_axe_start_in_systemd_scope,
)
from sase.axe.process import (
    AxeStartResult,
    restart_axe_daemon,
    start_axe_daemon,
    start_axe_daemon_result,
)


pytest_plugins = ("tests._axe_process_fixtures",)
pytestmark = pytest.mark.usefixtures("allow_axe_lifecycle_in_tests")


@pytest.fixture(autouse=True)
def disable_systemd_scope_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep existing spawn tests independent of the host's systemd setup."""
    monkeypatch.setenv(AXE_SYSTEMD_SCOPE_DISABLE_ENV, "1")


def test_compose_axe_daemon_env_strips_agent_and_chop_context() -> None:
    environ = {
        "PATH": "/bin",
        "SASE_AGENT": "1",
        "SASE_AGENT_NAME": "parent",
        "SASE_AGENT_AUTO_APPROVE": "1",
        "SASE_CHOP_NAME": "workflow_checks",
        "SASE_CHOP_LUMBERJACK": "hooks",
        "SASE_AXE_OTHER": "keep",
        "PYTEST_CURRENT_TEST": "tests/test_axe_process_start.py::test_env (call)",
        "PYTEST_VERSION": "9.0.2",
        "PYTEST_XDIST_WORKER": "gw3",
    }

    result = _compose_axe_daemon_env(environ)

    assert result == {
        "PATH": "/bin",
        "PYTEST_VERSION": "9.0.2",
        "SASE_AXE_OTHER": "keep",
        "SASE_AXE_START_SOURCE": "axe start",
    }
    assert environ["SASE_AGENT_NAME"] == "parent"


def test_wraps_start_command_in_unique_systemd_user_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(AXE_SYSTEMD_SCOPE_DISABLE_ENV)
    monkeypatch.setattr("sase.axe.systemd_scope.sys.platform", "linux")
    monkeypatch.setattr(
        "sase.axe.systemd_scope.shutil.which",
        lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else None,
    )
    monkeypatch.setattr("sase.axe.systemd_scope.os.getpid", lambda: 123)
    monkeypatch.setattr("sase.axe.systemd_scope.time.time_ns", lambda: 456)
    daemon_command = ["/usr/bin/sase", "axe", "start"]

    command, wrapped = wrap_axe_start_in_systemd_scope(daemon_command)

    assert wrapped is True
    assert command == [
        "/usr/bin/systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        "--unit=sase-axe-123-456",
        "--description=SASE axe orchestrator",
        "--",
        *daemon_command,
    ]


def test_does_not_wrap_start_command_without_systemd_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(AXE_SYSTEMD_SCOPE_DISABLE_ENV)
    monkeypatch.setattr("sase.axe.systemd_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.axe.systemd_scope.shutil.which", lambda _name: None)
    daemon_command = ["/usr/bin/sase", "axe", "start"]

    command, wrapped = wrap_axe_start_in_systemd_scope(daemon_command)

    assert wrapped is False
    assert command == daemon_command


def test_retries_unwrapped_when_systemd_scope_exits_before_pid_publish(
    monkeypatch: pytest.MonkeyPatch,
    axe_config: AxeConfig,
) -> None:
    monkeypatch.delenv(AXE_SYSTEMD_SCOPE_DISABLE_ENV)
    wrapped_process = MagicMock()
    wrapped_process.poll.return_value = 1
    fallback_process = MagicMock()
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(command: list[str], **kwargs: object) -> MagicMock:
        popen_calls.append((command, kwargs))
        return wrapped_process if len(popen_calls) == 1 else fallback_process

    daemon_command = ["/usr/bin/sase", "axe", "start"]
    scoped_command = ["/usr/bin/systemd-run", "--", *daemon_command]
    with (
        patch(
            "sase.axe._process_start._build_axe_start_command",
            return_value=daemon_command,
        ),
        patch(
            "sase.axe._process_start.wrap_axe_start_in_systemd_scope",
            return_value=(scoped_command, True),
        ),
        patch("sase.axe._process_start.subprocess.Popen", side_effect=fake_popen),
        patch(
            "sase.axe._process_start._wait_for_daemon_start",
            side_effect=[None, 4321],
        ),
    ):
        result = start_axe_daemon_result(axe_config, record_desired_state=False)

    assert result.status == "started"
    assert result.pid == 4321
    assert [call[0] for call in popen_calls] == [scoped_command, daemon_command]
    for _command, kwargs in popen_calls:
        lock_fds = kwargs["pass_fds"]
        assert isinstance(lock_fds, tuple)
        assert len(lock_fds) == 1
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert env["SASE_AXE_LIFECYCLE_LOCK_FD"] == str(lock_fds[0])


@patch("sase.axe._process_start.subprocess.Popen")
@patch("sase.axe._process_start._build_axe_start_command")
def test_start_axe_daemon_rejects_missing_daemon_cwd(
    mock_build_command: MagicMock,
    mock_popen: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    axe_config: AxeConfig,
) -> None:
    missing_home = tmp_path / "missing-home"
    monkeypatch.setenv("HOME", str(missing_home))
    monkeypatch.setattr(os.path, "expanduser", lambda _path: str(missing_home))
    mock_build_command.return_value = ["sase", "axe", "start"]

    result = start_axe_daemon_result(axe_config, record_desired_state=False)

    assert result.status == "failed"
    assert str(missing_home) in result.message
    assert "not an existing directory" in result.message
    mock_popen.assert_not_called()


@patch("sase.axe._process_start.subprocess.Popen")
@patch("sase.axe._process_probe.is_process_running", return_value=True)
def test_start_axe_daemon_returns_existing_pid(
    mock_is_running: MagicMock,
    mock_popen: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Already-running axe is neutral success."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("12345")

    assert start_axe_daemon(axe_config) == 12345
    mock_is_running.assert_called_once_with(12345)
    mock_popen.assert_not_called()


@patch(
    "sase.axe._process_start._build_axe_start_command",
    return_value=["/usr/bin/sase", "axe", "start"],
)
@patch("sase.axe._process_probe.is_process_running", return_value=True)
def test_repeated_start_axe_daemon_spawns_once_after_pid_appears(
    mock_is_running: MagicMock,
    _mock_build_command: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Repeated starts converge on the first live orchestrator PID."""
    pid_file = temp_state_dir / "orchestrator.pid"
    mock_proc = MagicMock()
    mock_proc.pid = 22222
    mock_proc.poll.return_value = None

    with patch("sase.axe._process_start.subprocess.Popen") as mock_popen:

        def fake_popen(*_args: object, **_kwargs: object) -> MagicMock:
            pid_file.write_text("22222")
            return mock_proc

        mock_popen.side_effect = fake_popen

        assert start_axe_daemon(axe_config) == 22222
        assert start_axe_daemon(axe_config) == 22222

    daemon_calls = [
        call
        for call in mock_popen.call_args_list
        if call.args
        and isinstance(call.args[0], list)
        and call.args[0][1:3] == ["axe", "start"]
    ]
    assert len(daemon_calls) == 1
    kwargs = daemon_calls[0].kwargs
    assert kwargs["pass_fds"]
    assert "SASE_AXE_LIFECYCLE_LOCK_FD" in kwargs["env"]
    assert kwargs["cwd"] == os.path.expanduser("~")
    mock_is_running.assert_any_call(22222)


def test_wait_for_daemon_start_waits_for_published_pid() -> None:
    """A live child is not success until the daemon PID file is readable."""
    mock_proc = MagicMock()
    mock_proc.pid = 99999
    mock_proc.poll.return_value = None

    with (
        patch(
            "sase.axe._process_start.get_pid_from_pid_files",
            side_effect=[None, 4321],
        ),
        patch("sase.axe._process_start.time.sleep", return_value=None),
    ):
        assert _wait_for_daemon_start(mock_proc, timeout=1.0) == 4321


def test_wait_for_daemon_start_does_not_return_child_pid_on_timeout() -> None:
    """Timeout without a PID file is failure, even if the child is alive."""
    mock_proc = MagicMock()
    mock_proc.pid = 99999
    mock_proc.poll.return_value = None

    with patch("sase.axe._process_start.get_pid_from_pid_files", return_value=None):
        assert _wait_for_daemon_start(mock_proc, timeout=0.0) is None


def test_wait_for_daemon_start_returns_none_when_child_exits() -> None:
    """A dead spawned child without a published PID is startup failure."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1

    with (
        patch(
            "sase.axe._process_start.get_pid_from_pid_files",
            return_value=None,
        ),
        patch("sase.axe._process_start.time.sleep", return_value=None),
    ):
        assert _wait_for_daemon_start(mock_proc, timeout=1.0) is None


def test_build_start_command_prefers_canonical_sase_from_ephemeral_workspace(
    tmp_path: Path,
    axe_config: AxeConfig,
) -> None:
    canonical = tmp_path / ".local" / "bin" / "sase"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("#!/bin/sh\n")
    ephemeral_python = (
        tmp_path
        / ".local"
        / "state"
        / "sase"
        / "workspaces"
        / "sase-org"
        / "sase"
        / "sase_42"
        / ".venv"
        / "bin"
        / "python"
    )
    ephemeral_python.parent.mkdir(parents=True)
    ephemeral_python.write_text("")

    with (
        patch("sase.axe._process_start.Path.home", return_value=tmp_path),
        patch("sase.axe._process_start.sys.executable", str(ephemeral_python)),
        patch("sase.axe._process_start.shutil.which", return_value=None),
        patch(
            "sase.axe._process_start._resolve_primary_workspace_sase",
            return_value=None,
        ),
    ):
        cmd = _build_axe_start_command(axe_config)

    assert cmd is not None
    assert cmd[0] == str(canonical)


def test_start_axe_daemon_result_reports_held_lock_without_pid(
    axe_config: AxeConfig,
    temp_state_dir: Path,
) -> None:
    """Start failure explains the held-lock/no-PID deadlock."""
    with (
        patch(
            "sase.axe._process_start.get_pid_from_pid_files",
            return_value=None,
        ),
        patch(
            "sase.axe._process_start._acquire_lifecycle_lock_for_start",
            return_value=None,
        ),
        patch(
            "sase.axe._process_start.probe_orchestrator",
            return_value=AxeOrchestratorProbe(
                lock_held=True,
                lock_holder_pid=None,
                orchestrator_pid_file_pid=None,
                legacy_pid=None,
                running_pid=None,
            ),
        ),
    ):
        result = start_axe_daemon_result(axe_config)

    assert result.status == "blocked"
    assert result.pid is None
    assert "sase axe stop --force" in result.message
    marker = read_desired_state()
    assert marker is not None
    assert marker.state == "running"
    assert marker.source == "axe start"
    assert (temp_state_dir / "wedged_lifecycle_lock.json").exists()


def _spawn_unpublished_lock_holder(lock_path: Path) -> subprocess.Popen[str]:
    child_code = "\n".join(
        [
            "import fcntl",
            "import os",
            "import sys",
            "import time",
            "fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o600)",
            "fcntl.flock(fd, fcntl.LOCK_EX)",
            "pid = os.getpid()",
            "os.ftruncate(fd, 0)",
            "os.write(fd, f'{pid}\\n'.encode())",
            "os.fsync(fd)",
            "print(pid, flush=True)",
            "time.sleep(30)",
        ]
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", child_code, str(lock_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    line = holder.stdout.readline().strip()
    assert line, holder.stderr.read() if holder.stderr is not None else ""
    assert int(line) == holder.pid
    return holder


def test_ensure_recovers_unpublished_lock_holder_after_grace(
    axe_config: AxeConfig,
    temp_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure terminates an aged lock holder and retries startup once."""
    holder = _spawn_unpublished_lock_holder(temp_state_dir / "orchestrator.lock")
    spawned: list[subprocess.Popen[bytes]] = []
    acquire_calls = 0
    real_popen = subprocess.Popen

    def acquire_for_start() -> AxeLifecycleLock | None:
        nonlocal acquire_calls
        acquire_calls += 1
        if acquire_calls <= 2:
            return None
        return AxeLifecycleLock.acquire(blocking=False)

    def spawn_for_start(
        command: list[str],
        *args: object,
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        if command == ["fake-sase"]:
            command = [
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ]
        process = real_popen(command, *args, **kwargs)
        if command[0] == sys.executable and "time.sleep(30)" in command[-1]:
            spawned.append(process)
        return process

    monkeypatch.setenv("SASE_AXE_WEDGED_LOCK_GRACE_SECONDS", "60")
    try:
        with (
            patch(
                "sase.axe._process_start._acquire_lifecycle_lock_for_start",
                side_effect=acquire_for_start,
            ),
            patch(
                "sase.axe._process_start._build_axe_start_command",
                return_value=["fake-sase"],
            ),
            patch(
                "sase.axe._process_start.subprocess.Popen",
                side_effect=spawn_for_start,
            ),
            patch(
                "sase.axe._process_start._wait_for_daemon_start",
                side_effect=lambda process: process.pid,
            ),
            patch(
                "sase.axe._process_start.time.time",
                side_effect=[100.0, 161.0],
            ),
            patch(
                "sase.axe._process_start._notify_wedged_lock_recovery"
            ) as notify_recovery,
        ):
            first = start_axe_daemon_result(axe_config)
            result = ensure_axe(
                running_fn=lambda: False,
                start_fn=lambda **kwargs: start_axe_daemon_result(axe_config, **kwargs),
                notify_fn=lambda _downtime, _pid: "healed-notification",
            )

        assert first.status == "blocked"
        assert result.status == "healed"
        assert result.pid == spawned[0].pid
        assert holder.poll() is not None
        assert not (temp_state_dir / "wedged_lifecycle_lock.json").exists()
        notify_recovery.assert_called_once_with(holder.pid, spawned[0].pid)
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=2)
        for process in spawned:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2)


def test_unpublished_lock_holder_that_publishes_during_grace_is_preserved(
    axe_config: AxeConfig,
    temp_state_dir: Path,
) -> None:
    """A starter that publishes its PID during grace is never signaled."""
    holder = _spawn_unpublished_lock_holder(temp_state_dir / "orchestrator.lock")
    try:
        with (
            patch(
                "sase.axe._process_start._acquire_lifecycle_lock_for_start",
                return_value=None,
            ),
            patch("sase.axe._process_start.time.time", return_value=100.0),
        ):
            first = start_axe_daemon_result(axe_config)

        (temp_state_dir / "orchestrator.pid").write_text(f"{holder.pid}\n")
        with patch("sase.axe._process_stop.terminate_process") as terminate_process:
            second = start_axe_daemon_result(axe_config)

        assert first.status == "blocked"
        assert second.status == "already_running"
        assert second.pid == holder.pid
        assert holder.poll() is None
        assert not (temp_state_dir / "wedged_lifecycle_lock.json").exists()
        terminate_process.assert_not_called()
    finally:
        holder.terminate()
        holder.wait(timeout=2)


def test_restart_axe_daemon_returns_verified_result_pid(axe_config: AxeConfig) -> None:
    result = AxeStartResult(status="started", pid=2468, verified=True)
    with patch(
        "sase.axe._process_restart.restart_axe_daemon_result",
        return_value=result,
    ) as mock_restart:
        assert restart_axe_daemon(axe_config) == 2468

    mock_restart.assert_called_once_with(axe_config)
