from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pytest import MonkeyPatch

from sase.integrations import chat_install
from sase.integrations.chat_install import (
    ChatInstallConfig,
    load_chat_install_config,
    resolve_primary_workspace_for_chat_install,
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
    assert result.message == (
        "chat_install.command is not configured; update was not started."
    )
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
    assert (
        result.message
        == "Could not resolve the primary SASE workspace; update was not started."
    )


def test_resolves_registered_sase_workspace_outside_workspace(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    workspace = tmp_path / "sase"
    workspace.mkdir()
    _write_project_file(tmp_path, "sase", workspace)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    with (
        patch("sase.integrations.chat_install.Path.home", return_value=tmp_path),
        patch("sase.bead.workspace.resolve_primary_workspace") as fallback,
    ):
        result = resolve_primary_workspace_for_chat_install()

    assert result == workspace
    fallback.assert_not_called()


def test_resolves_registered_sase_workspace_over_cwd_project(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    sase_workspace = tmp_path / "sase"
    plugin_workspace = tmp_path / "sase-telegram"
    sase_workspace.mkdir()
    plugin_workspace.mkdir()
    _write_project_file(tmp_path, "sase", sase_workspace)
    monkeypatch.chdir(plugin_workspace)

    with (
        patch("sase.integrations.chat_install.Path.home", return_value=tmp_path),
        patch(
            "sase.bead.workspace.resolve_primary_workspace",
            return_value=plugin_workspace,
        ) as fallback,
    ):
        result = resolve_primary_workspace_for_chat_install()

    assert result == sase_workspace
    fallback.assert_not_called()


def test_resolves_registered_sase_workspace_falls_back_when_unavailable(
    tmp_path: Path,
) -> None:
    fallback_workspace = tmp_path / "current-project"
    fallback_workspace.mkdir()
    _write_project_file(tmp_path, "sase", tmp_path / "deleted")

    with (
        patch("sase.integrations.chat_install.Path.home", return_value=tmp_path),
        patch(
            "sase.bead.workspace.resolve_primary_workspace",
            return_value=fallback_workspace,
        ) as fallback,
    ):
        result = resolve_primary_workspace_for_chat_install()

    assert result == fallback_workspace
    fallback.assert_called_once_with()


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
    assert result.message == "A chat update worker is already running."


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
    assert result.job_id is not None
    assert result.status_path is not None
    assert result.message.startswith("Update worker started; log: ")
    assert result.pid == 1234
    args, kwargs = popen.call_args
    cmd = args[0]
    assert "--job-id" in cmd
    assert cmd[cmd.index("--job-id") + 1] == result.job_id
    assert "--status-path" in cmd
    assert cmd[cmd.index("--status-path") + 1] == str(result.status_path)
    assert "--log-path" in cmd
    assert cmd[cmd.index("--log-path") + 1] == str(result.log_path)
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


def test_run_worker_ignores_unrelated_inherited_lock_fd(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    provider = MagicMock()
    provider.sync_workspace.return_value = (False, "conflict")
    lock_path = tmp_path / "install.lock"
    unrelated_fd = os.open(tmp_path / "unrelated.fd", os.O_RDWR | os.O_CREAT, 0o600)
    monkeypatch.setenv(chat_install._LOCK_FD_ENV, str(unrelated_fd))

    try:
        with (
            patch.object(chat_install, "_LOCK_PATH", lock_path),
            patch(
                "sase.integrations.chat_install.load_chat_install_config",
                return_value=ChatInstallConfig(command="install", restart_attempts=1),
            ),
            patch("sase.integrations.chat_install.stop_axe_daemon", return_value=True),
            patch(
                "sase.integrations.chat_install.get_vcs_provider", return_value=provider
            ),
            patch("sase.integrations.chat_install.subprocess.run") as run,
            patch("sase.integrations.chat_install.start_axe_daemon", return_value=999),
            patch("sase.integrations.chat_install.is_axe_running", return_value=True),
        ):
            assert run_worker(tmp_path) == 4

        os.fstat(unrelated_fd)
        assert chat_install._LOCK_FD_ENV not in os.environ
        run.assert_not_called()
    finally:
        os.close(unrelated_fd)


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


def test_run_worker_writes_success_completion_record(tmp_path: Path) -> None:
    status_path = tmp_path / "completion.json"
    log_path = tmp_path / "worker.log"

    with (
        patch(
            "sase.integrations.chat_install.load_chat_install_config",
            return_value=ChatInstallConfig(
                command="install", sync_workspace=False, restart_attempts=1
            ),
        ),
        patch("sase.integrations.chat_install.stop_axe_daemon", return_value=True),
        patch(
            "sase.integrations.chat_install.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ),
        patch("sase.integrations.chat_install.start_axe_daemon", return_value=999),
        patch("sase.integrations.chat_install.is_axe_running", return_value=True),
    ):
        assert (
            run_worker(
                tmp_path,
                job_id="job-1",
                status_path=status_path,
                log_path=log_path,
            )
            == 0
        )

    record = json.loads(status_path.read_text())
    assert record["job_id"] == "job-1"
    assert record["status"] == "success"
    assert record["exit_code"] == 0
    assert record["log_path"] == str(log_path)
    assert record["workspace"] == str(tmp_path)
    assert record["restart_succeeded"] is True
    assert record["message"] == "Update completed successfully."


def test_run_worker_writes_failure_completion_record(tmp_path: Path) -> None:
    status_path = tmp_path / "completion.json"
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
        assert run_worker(tmp_path, job_id="job-2", status_path=status_path) == 4

    run.assert_not_called()
    record = json.loads(status_path.read_text())
    assert record["job_id"] == "job-2"
    assert record["status"] == "failed"
    assert record["exit_code"] == 4
    assert record["restart_succeeded"] is True
    assert record["message"] == "Update failed with exit code 4."


def test_run_worker_marks_restart_failure_as_failed_completion(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "completion.json"

    with (
        patch(
            "sase.integrations.chat_install.load_chat_install_config",
            return_value=ChatInstallConfig(
                command="install", sync_workspace=False, restart_attempts=2
            ),
        ),
        patch("sase.integrations.chat_install.stop_axe_daemon", return_value=True),
        patch(
            "sase.integrations.chat_install.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ),
        patch("sase.integrations.chat_install.start_axe_daemon", return_value=None),
        patch("sase.integrations.chat_install.is_axe_running", return_value=False),
        patch("sase.integrations.chat_install.time.sleep"),
    ):
        assert run_worker(tmp_path, job_id="job-3", status_path=status_path) == 5

    record = json.loads(status_path.read_text())
    assert record["status"] == "failed"
    assert record["exit_code"] == 5
    assert record["restart_succeeded"] is False
    assert record["message"] == "Update failed with exit code 5; axe restart failed."


def _write_project_file(home: Path, project_name: str, workspace: Path) -> Path:
    project_dir = home / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{project_name}.gp"
    project_file.write_text(f"WORKSPACE_DIR: {workspace}\nNAME: example\n")
    return project_file
