from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pytest import MonkeyPatch

from sase.integrations import chat_install
from sase.integrations._chat_install_cli import main as chat_install_cli_main
from sase.integrations.chat_install import (
    _ChatInstallConfig,
    _load_chat_install_config,
    read_chat_install_status,
    _run_worker,
    start_chat_install_worker,
)


def test__load_chat_install_config_defaults() -> None:
    with patch("sase.integrations.chat_install.load_merged_config", return_value={}):
        assert _load_chat_install_config() == _ChatInstallConfig()


def test__load_chat_install_config_normalizes_remaining_values() -> None:
    with patch(
        "sase.integrations.chat_install.load_merged_config",
        return_value={
            "chat_install": {
                "command": "stale custom command",
                "sync_workspace": False,
                "timeout_seconds": "12",
                "restart_attempts": "2",
            }
        },
    ):
        assert _load_chat_install_config() == _ChatInstallConfig(
            timeout_seconds=12,
            restart_attempts=2,
        )


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
        ):
            result = start_chat_install_worker()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    assert result.status == "already_running"
    assert result.message == "A chat update worker is already running."


def test_start_worker_launches_detached_process_with_empty_config(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".sase" / "chat_install"
    lock_path = state_dir / "install.lock"
    log_dir = state_dir / "logs"
    completions_dir = state_dir / "completions"
    jobs_dir = state_dir / "jobs"

    with (
        patch.object(chat_install, "_STATE_DIR", state_dir),
        patch.object(chat_install, "_LOCK_PATH", lock_path),
        patch.object(chat_install, "_LOG_DIR", log_dir),
        patch.object(chat_install, "_COMPLETIONS_DIR", completions_dir),
        patch.object(chat_install, "_JOBS_DIR", jobs_dir),
        patch(
            "sase.integrations.chat_install.subprocess.Popen",
            return_value=SimpleNamespace(pid=1234),
        ) as popen,
        patch("sase.integrations.chat_install._lock_is_held", return_value=True),
    ):
        result = start_chat_install_worker()
        status = read_chat_install_status(result.job_id or "")

    assert result.status == "launched"
    assert result.workspace is None
    assert result.log_path is not None
    assert result.job_id is not None
    assert result.status_path is not None
    assert result.message.startswith("Update worker started; log: ")
    assert result.pid == 1234
    assert status.status == "running"
    assert status.job_id == result.job_id
    assert status.log_path == result.log_path
    assert status.completion_path == result.status_path
    assert status.workspace is None
    args, kwargs = popen.call_args
    cmd = args[0]
    assert "--workspace" not in cmd
    assert "--job-id" in cmd
    assert cmd[cmd.index("--job-id") + 1] == result.job_id
    assert "--status-path" in cmd
    assert cmd[cmd.index("--status-path") + 1] == str(result.status_path)
    assert "--log-path" in cmd
    assert cmd[cmd.index("--log-path") + 1] == str(result.log_path)
    assert "cwd" not in kwargs
    assert kwargs["start_new_session"] is True
    assert kwargs["pass_fds"]
    assert kwargs["env"][chat_install._LOCK_FD_ENV] == str(kwargs["pass_fds"][0])


def test_worker_cli_no_longer_requires_workspace(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def run_worker(**kwargs: object) -> int:
        seen.update(kwargs)
        return 0

    code = chat_install_cli_main(
        [
            "--job-id",
            "job-1",
            "--status-path",
            str(tmp_path / "status.json"),
            "--log-path",
            str(tmp_path / "worker.log"),
        ],
        run_worker=run_worker,
    )

    assert code == 0
    assert seen == {
        "job_id": "job-1",
        "status_path": tmp_path / "status.json",
        "log_path": tmp_path / "worker.log",
    }


def test_status_reader_returns_completion_success_without_workspace(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".sase" / "chat_install"
    completions_dir = state_dir / "completions"
    completions_dir.mkdir(parents=True)
    completion_path = completions_dir / "job_1.json"
    log_path = tmp_path / "worker.log"
    completion_path.write_text(
        json.dumps(
            {
                "job_id": "job_1",
                "status": "success",
                "exit_code": 0,
                "log_path": str(log_path),
                "started_at": "2026-05-06T15:00:00+00:00",
                "completed_at": "2026-05-06T15:01:00+00:00",
                "restart_succeeded": True,
                "message": "Already up to date.",
            }
        )
    )

    with (
        patch.object(chat_install, "_STATE_DIR", state_dir),
        patch.object(chat_install, "_COMPLETIONS_DIR", completions_dir),
        patch.object(chat_install, "_LOCK_PATH", state_dir / "install.lock"),
    ):
        result = read_chat_install_status("job_1")

    assert result.status == "succeeded"
    assert result.message == "Already up to date."
    assert result.log_path == log_path
    assert result.completion_path == completion_path
    assert result.workspace is None
    assert result.exit_code == 0
    assert result.restart_succeeded is True


def test_status_reader_returns_failure_for_malformed_completion(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".sase" / "chat_install"
    completions_dir = state_dir / "completions"
    completions_dir.mkdir(parents=True)
    (completions_dir / "job_bad.json").write_text("{invalid")

    with (
        patch.object(chat_install, "_STATE_DIR", state_dir),
        patch.object(chat_install, "_COMPLETIONS_DIR", completions_dir),
        patch.object(chat_install, "_LOCK_PATH", state_dir / "install.lock"),
    ):
        result = read_chat_install_status("job_bad")

    assert result.status == "failed"
    assert "malformed" in result.message


def test_status_reader_returns_not_found_for_unknown_job(tmp_path: Path) -> None:
    state_dir = tmp_path / ".sase" / "chat_install"

    with (
        patch.object(chat_install, "_STATE_DIR", state_dir),
        patch.object(chat_install, "_COMPLETIONS_DIR", state_dir / "completions"),
        patch.object(chat_install, "_JOBS_DIR", state_dir / "jobs"),
        patch.object(chat_install, "_LOCK_PATH", state_dir / "install.lock"),
    ):
        result = read_chat_install_status("missing")

    assert result.status == "not_found"


def test_status_reader_returns_running_when_known_job_holds_lock(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".sase" / "chat_install"
    jobs_dir = state_dir / "jobs"
    jobs_dir.mkdir(parents=True)
    lock_path = state_dir / "install.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (jobs_dir / "job_running.json").write_text(
        json.dumps(
            {
                "job_id": "job_running",
                "status": "running",
                "message": "Update worker started.",
                "log_path": str(tmp_path / "worker.log"),
                "workspace": None,
                "status_path": str(state_dir / "completions" / "job_running.json"),
                "pid": 1234,
                "started_at": "2026-05-06T15:00:00+00:00",
                "finished_at": None,
            }
        )
    )

    try:
        with (
            patch.object(chat_install, "_STATE_DIR", state_dir),
            patch.object(chat_install, "_COMPLETIONS_DIR", state_dir / "completions"),
            patch.object(chat_install, "_JOBS_DIR", jobs_dir),
            patch.object(chat_install, "_LOCK_PATH", lock_path),
        ):
            result = read_chat_install_status("job_running")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    assert result.status == "running"
    assert result.message == "Update worker started."
    assert result.workspace is None


def test_run_worker_runs_sase_update_json_and_uses_payload_message(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "completion.json"
    log_path = tmp_path / "worker.log"
    seen: dict[str, object] = {}
    payload = {
        "schema_version": 2,
        "dry_run": False,
        "changed": True,
        "counts": {"updated": 2, "already_current": 1, "removed": 0},
        "packages": [
            {
                "name": "sase",
                "role": "primary",
                "kind": "upgraded",
                "old_version": "0.5.0",
                "new_version": "0.6.1",
            },
            {
                "name": "sase-github",
                "role": "plugin",
                "kind": "upgraded",
                "old_version": "0.3.2",
                "new_version": "0.4.0",
            },
        ],
    }

    def run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    with (
        patch(
            "sase.integrations.chat_install._load_chat_install_config",
            return_value=_ChatInstallConfig(timeout_seconds=12, restart_attempts=1),
        ),
        patch("sase.integrations.chat_install.subprocess.run", side_effect=run),
        patch("sase.integrations.chat_install.start_axe_daemon") as start,
        patch("sase.integrations.chat_install.is_axe_running", return_value=True),
    ):
        assert (
            _run_worker(
                job_id="job-1",
                status_path=status_path,
                log_path=log_path,
            )
            == 0
        )

    assert seen["argv"] == [sys.executable, "-m", "sase", "update", "--json"]
    assert seen["kwargs"] == {
        "text": True,
        "capture_output": True,
        "timeout": 12,
    }
    start.assert_not_called()
    record = json.loads(status_path.read_text())
    assert record["job_id"] == "job-1"
    assert record["status"] == "success"
    assert record["exit_code"] == 0
    assert record["log_path"] == str(log_path)
    assert record["workspace"] is None
    assert record["restart_succeeded"] is True
    assert record["message"] == (
        "Update completed: sase 0.5.0 to 0.6.1, 1 plugin updated."
    )


def test_run_worker_summarizes_dev_update_core_package(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "completion.json"
    payload = {
        "schema_version": 2,
        "dry_run": False,
        "mode": "dev",
        "changed": True,
        "counts": {
            "updated": 3,
            "already_current": 0,
            "removed": 0,
            "skipped": 0,
            "failed": 0,
        },
        "packages": [
            {
                "name": "sase",
                "role": "host",
                "status": "updated",
                "old_version": "0.5.0",
                "new_version": "0.6.1",
            },
            {
                "name": "sase-core-rs",
                "role": "core",
                "status": "updated",
                "old_version": "0.3.1",
                "new_version": "0.3.2",
            },
            {
                "name": "sase-github",
                "role": "plugin",
                "status": "updated",
                "old_version": "0.3.2",
                "new_version": "0.4.0",
            },
        ],
    }

    with (
        patch(
            "sase.integrations.chat_install._load_chat_install_config",
            return_value=_ChatInstallConfig(restart_attempts=1),
        ),
        patch(
            "sase.integrations.chat_install.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(payload), stderr=""
            ),
        ),
        patch("sase.integrations.chat_install.is_axe_running", return_value=True),
    ):
        assert _run_worker(job_id="job-core", status_path=status_path) == 0

    record = json.loads(status_path.read_text())
    assert record["message"] == (
        "Update completed: sase 0.5.0 to 0.6.1, core 0.3.1 to 0.3.2, 1 plugin updated."
    )


def test_run_worker_reports_already_up_to_date(tmp_path: Path) -> None:
    status_path = tmp_path / "completion.json"
    payload = {
        "schema_version": 2,
        "dry_run": False,
        "changed": False,
        "counts": {"updated": 0, "already_current": 3, "removed": 0},
        "packages": [],
    }

    with (
        patch(
            "sase.integrations.chat_install._load_chat_install_config",
            return_value=_ChatInstallConfig(restart_attempts=1),
        ),
        patch(
            "sase.integrations.chat_install.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(payload), stderr=""
            ),
        ),
        patch("sase.integrations.chat_install.is_axe_running", return_value=True),
    ):
        assert _run_worker(job_id="job-2", status_path=status_path) == 0

    record = json.loads(status_path.read_text())
    assert record["message"] == "Already up to date."


def test_run_worker_surfaces_update_json_error(tmp_path: Path) -> None:
    status_path = tmp_path / "completion.json"
    payload = {
        "schema_version": 2,
        "error": "This Python environment is not managed by uv tool.",
    }

    with (
        patch(
            "sase.integrations.chat_install._load_chat_install_config",
            return_value=_ChatInstallConfig(restart_attempts=1),
        ),
        patch(
            "sase.integrations.chat_install.subprocess.run",
            return_value=SimpleNamespace(
                returncode=1, stdout=json.dumps(payload), stderr=""
            ),
        ),
        patch("sase.integrations.chat_install.is_axe_running", return_value=True),
    ):
        assert _run_worker(job_id="job-3", status_path=status_path) == 1

    record = json.loads(status_path.read_text())
    assert record["status"] == "failed"
    assert record["exit_code"] == 1
    assert record["message"] == (
        "Update failed: This Python environment is not managed by uv tool."
    )


def test_run_worker_falls_back_when_update_json_is_malformed(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "completion.json"

    with (
        patch(
            "sase.integrations.chat_install._load_chat_install_config",
            return_value=_ChatInstallConfig(restart_attempts=1),
        ),
        patch(
            "sase.integrations.chat_install.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="not json", stderr=""),
        ),
        patch("sase.integrations.chat_install.is_axe_running", return_value=True),
    ):
        assert _run_worker(job_id="job-4", status_path=status_path) == 0

    record = json.loads(status_path.read_text())
    assert record["message"] == "Update completed successfully."


def test_run_worker_maps_update_timeout_to_124(tmp_path: Path) -> None:
    status_path = tmp_path / "completion.json"

    with (
        patch(
            "sase.integrations.chat_install._load_chat_install_config",
            return_value=_ChatInstallConfig(timeout_seconds=12, restart_attempts=1),
        ),
        patch(
            "sase.integrations.chat_install.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["sase", "update"], timeout=12, output="partial", stderr="err"
            ),
        ),
        patch("sase.integrations.chat_install.is_axe_running", return_value=True),
    ):
        assert _run_worker(job_id="job-5", status_path=status_path) == 124

    record = json.loads(status_path.read_text())
    assert record["status"] == "failed"
    assert record["exit_code"] == 124
    assert record["message"] == "Update failed with exit code 124."


def test_run_worker_starts_axe_when_down_after_update(tmp_path: Path) -> None:
    status_path = tmp_path / "completion.json"
    payload = {"schema_version": 2, "dry_run": False, "changed": False}

    with (
        patch(
            "sase.integrations.chat_install._load_chat_install_config",
            return_value=_ChatInstallConfig(restart_attempts=2),
        ),
        patch(
            "sase.integrations.chat_install.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(payload), stderr=""
            ),
        ),
        patch(
            "sase.integrations.chat_install.start_axe_daemon", return_value=999
        ) as start,
        patch(
            "sase.integrations.chat_install.is_axe_running",
            side_effect=[False, True],
        ),
        patch("sase.integrations.chat_install.time.sleep"),
    ):
        assert _run_worker(job_id="job-6", status_path=status_path) == 0

    assert start.call_count == 1
    record = json.loads(status_path.read_text())
    assert record["restart_succeeded"] is True
    assert record["message"] == "Already up to date."


def test_run_worker_marks_axe_start_failure_as_exit_code_5(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "completion.json"
    payload = {"schema_version": 2, "dry_run": False, "changed": False}

    with (
        patch(
            "sase.integrations.chat_install._load_chat_install_config",
            return_value=_ChatInstallConfig(restart_attempts=2),
        ),
        patch(
            "sase.integrations.chat_install.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(payload), stderr=""
            ),
        ),
        patch("sase.integrations.chat_install.start_axe_daemon", return_value=None),
        patch("sase.integrations.chat_install.is_axe_running", return_value=False),
        patch("sase.integrations.chat_install.time.sleep"),
    ):
        assert _run_worker(job_id="job-7", status_path=status_path) == 5

    record = json.loads(status_path.read_text())
    assert record["status"] == "failed"
    assert record["exit_code"] == 5
    assert record["restart_succeeded"] is False
    assert record["message"] == "Update failed with exit code 5; axe restart failed."


def test_run_worker_ignores_unrelated_inherited_lock_fd(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lock_path = tmp_path / "install.lock"
    unrelated_fd = os.open(tmp_path / "unrelated.fd", os.O_RDWR | os.O_CREAT, 0o600)
    monkeypatch.setenv(chat_install._LOCK_FD_ENV, str(unrelated_fd))
    payload = {"schema_version": 2, "dry_run": False, "changed": False}

    try:
        with (
            patch.object(chat_install, "_LOCK_PATH", lock_path),
            patch(
                "sase.integrations.chat_install._load_chat_install_config",
                return_value=_ChatInstallConfig(restart_attempts=1),
            ),
            patch(
                "sase.integrations.chat_install.subprocess.run",
                return_value=SimpleNamespace(
                    returncode=0, stdout=json.dumps(payload), stderr=""
                ),
            ),
            patch("sase.integrations.chat_install.is_axe_running", return_value=True),
        ):
            assert _run_worker() == 0

        os.fstat(unrelated_fd)
        assert chat_install._LOCK_FD_ENV not in os.environ
    finally:
        os.close(unrelated_fd)
