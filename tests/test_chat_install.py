from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.integrations import chat_install
from sase.integrations.chat_install import (
    ChatInstallConfig,
    load_chat_install_config,
    run_worker,
    start_chat_install_worker,
)


def test_load_chat_install_config_defaults() -> None:
    with patch("sase.integrations.chat_install.load_merged_config", return_value={}):
        assert load_chat_install_config() == ChatInstallConfig(command="")


def test_load_chat_install_config_normalizes_values() -> None:
    with patch(
        "sase.integrations.chat_install.load_merged_config",
        return_value={
            "chat_install": {
                "command": "  install_sase_github  ",
                "sync_workspace": False,
                "timeout_seconds": "12",
                "restart_attempts": "2",
            }
        },
    ):
        assert load_chat_install_config() == ChatInstallConfig(
            command="install_sase_github",
            sync_workspace=False,
            timeout_seconds=12,
            restart_attempts=2,
        )


def test_start_worker_rejects_missing_command() -> None:
    with (
        patch(
            "sase.integrations.chat_install.load_chat_install_config",
            return_value=ChatInstallConfig(command=""),
        ),
        patch("sase.integrations.chat_install.subprocess.Popen") as popen,
    ):
        result = start_chat_install_worker()

    assert result.status == "config_missing_command"
    popen.assert_not_called()


def test_start_worker_reports_workspace_resolution_failed(tmp_path: Path) -> None:
    state_dir = tmp_path / ".sase" / "chat_install"
    with (
        patch.object(chat_install, "_STATE_DIR", state_dir),
        patch.object(chat_install, "_LOCK_PATH", state_dir / "install.lock"),
        patch(
            "sase.integrations.chat_install.load_chat_install_config",
            return_value=ChatInstallConfig(command="true"),
        ),
        patch(
            "sase.integrations.chat_install.resolve_primary_workspace_for_chat_install",
            return_value=None,
        ),
    ):
        result = start_chat_install_worker()

    assert result.status == "workspace_resolution_failed"


def test_start_worker_reports_existing_lock(tmp_path: Path) -> None:
    state_dir = tmp_path / ".sase" / "chat_install"
    state_dir.mkdir(parents=True)
    lock_path = state_dir / "install.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with (
            patch("sase.integrations.chat_install.Path.home", return_value=tmp_path),
            patch.object(chat_install, "_STATE_DIR", state_dir),
            patch.object(chat_install, "_LOCK_PATH", lock_path),
            patch(
                "sase.integrations.chat_install.load_chat_install_config",
                return_value=ChatInstallConfig(command="true"),
            ),
        ):
            result = start_chat_install_worker()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    assert result.status == "already_running"


def test_start_worker_launches_detached_process(tmp_path: Path) -> None:
    state_dir = tmp_path / ".sase" / "chat_install"
    lock_path = state_dir / "install.lock"
    log_dir = state_dir / "logs"
    workspace = tmp_path / "repo"
    workspace.mkdir()

    with (
        patch.object(chat_install, "_STATE_DIR", state_dir),
        patch.object(chat_install, "_LOCK_PATH", lock_path),
        patch.object(chat_install, "_LOG_DIR", log_dir),
        patch(
            "sase.integrations.chat_install.load_chat_install_config",
            return_value=ChatInstallConfig(command="true"),
        ),
        patch(
            "sase.integrations.chat_install.resolve_primary_workspace_for_chat_install",
            return_value=workspace,
        ),
        patch(
            "sase.integrations.chat_install.subprocess.Popen",
            return_value=SimpleNamespace(pid=1234),
        ) as popen,
    ):
        result = start_chat_install_worker()

    assert result.status == "launched"
    assert result.workspace == workspace
    assert result.log_path is not None
    assert result.pid == 1234
    _args, kwargs = popen.call_args
    assert kwargs["cwd"] == str(workspace)
    assert kwargs["start_new_session"] is True
    assert kwargs["pass_fds"]
    assert kwargs["env"][chat_install._LOCK_FD_ENV] == str(kwargs["pass_fds"][0])


def test_run_worker_skips_install_when_sync_fails(tmp_path: Path) -> None:
    provider = MagicMock()
    provider.sync_workspace.return_value = (False, "conflict")

    with (
        patch(
            "sase.integrations.chat_install.load_chat_install_config",
            return_value=ChatInstallConfig(command="install", restart_attempts=1),
        ),
        patch("sase.integrations.chat_install.stop_axe_daemon", return_value=True),
        patch("sase.integrations.chat_install.get_vcs_provider", return_value=provider),
        patch("sase.integrations.chat_install.subprocess.run") as run,
        patch("sase.integrations.chat_install.start_axe_daemon", return_value=999),
        patch("sase.integrations.chat_install.is_axe_running", return_value=True),
    ):
        assert run_worker(tmp_path) == 4

    run.assert_not_called()


def test_run_worker_restarts_axe_when_command_fails(tmp_path: Path) -> None:
    provider = MagicMock()
    provider.sync_workspace.return_value = (True, None)

    with (
        patch(
            "sase.integrations.chat_install.load_chat_install_config",
            return_value=ChatInstallConfig(command="install", restart_attempts=2),
        ),
        patch("sase.integrations.chat_install.stop_axe_daemon", return_value=False),
        patch("sase.integrations.chat_install.get_vcs_provider", return_value=provider),
        patch(
            "sase.integrations.chat_install.subprocess.run",
            return_value=SimpleNamespace(returncode=17, stdout="", stderr=""),
        ),
        patch(
            "sase.integrations.chat_install.start_axe_daemon",
            side_effect=[None, 999],
        ) as start,
        patch("sase.integrations.chat_install.is_axe_running", return_value=True),
        patch("sase.integrations.chat_install.time.sleep"),
    ):
        assert run_worker(tmp_path) == 17

    assert start.call_count == 2
