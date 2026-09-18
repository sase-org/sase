"""Coverage for SSH sudo handoff helpers."""

from __future__ import annotations

import os
import signal
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from sase.notification_gates.models import GateError
from sase.sudo.ssh import (
    _encode_ssh_remote_command,
    _probe_remote_executor_liveness,
    allocate_remote_sudo_paths,
    cleanup_remote_sudo,
    remote_supports_detached_execution,
    run_remote_sudo,
    run_remote_sudo_detached,
    wait_for_remote_sudo_ledger,
)

from tests._sudo_ssh_fake import (
    FakeOpenSSHEndpoint,
    current_process_identity,
    openssh_join_remote_argv,
)


def _manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "sudo-1",
        "cwd": "/tmp/remote cwd",
    }


def test_openssh_join_drops_quotes_across_separate_argv_items() -> None:
    _tty, host, joined = openssh_join_remote_argv(
        ["ssh", "-t", "target", "sh", "-c", "mkdir -p /tmp/remote cwd"]
    )
    assert host == "target"
    assert joined == "sh -c mkdir -p /tmp/remote cwd"


def test_encode_ssh_remote_command_quotes_paths_with_spaces() -> None:
    encoded = _encode_ssh_remote_command(
        "sase", "sudo", "exec", "--manifest", "/tmp/remote cwd/manifest.json"
    )
    assert encoded == "sase sudo exec --manifest '/tmp/remote cwd/manifest.json'"


def test_run_remote_sudo_stages_executes_fetches_and_cleans(tmp_path: Path) -> None:
    fake = FakeOpenSSHEndpoint(tmp_path)
    paths = allocate_remote_sudo_paths(base=str(tmp_path / "remote cwd"))
    ledger = run_remote_sudo(
        "target",
        _manifest(),
        manifest_sha256="abc",
        command_runner=fake,
        paths=paths,
    )
    assert ledger["outcome"] == "completed"
    assert ledger["request_id"] == "sudo-1"
    assert not Path(paths["directory"]).exists()
    assert any("sase sudo exec --contract" in command for command in fake.joined)
    assert any(
        "--manifest" in command and "remote cwd" in command for command in fake.joined
    )
    staged = next(command for command in fake.joined if "mkdir -p -m 700" in command)
    assert "exit 11" in staged
    assert "exit 13" in staged


def test_run_remote_sudo_rejects_contract_mismatch(tmp_path: Path) -> None:
    fake = FakeOpenSSHEndpoint(tmp_path, capabilities=())

    def broken(argv: list[str], **kwargs: Any) -> Any:
        del kwargs
        _tty, _host, joined = openssh_join_remote_argv(argv)
        if "exec --contract" in joined:
            import subprocess

            return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")
        return fake(argv, **{})

    with pytest.raises(GateError) as excinfo:
        run_remote_sudo(
            "target",
            _manifest(),
            manifest_sha256="abc",
            command_runner=broken,
        )
    assert excinfo.value.code == "remote_sudo_contract_mismatch"


def test_run_remote_sudo_timeout_after_spawn_retains_handoff(tmp_path: Path) -> None:
    fake = FakeOpenSSHEndpoint(tmp_path)
    paths = allocate_remote_sudo_paths(base=str(tmp_path / "keep"))
    os.environ["SASE_FAKE_EXEC_SLEEP"] = "2"
    try:
        with pytest.raises(GateError) as excinfo:
            run_remote_sudo(
                "target",
                _manifest(),
                manifest_sha256="abc",
                command_runner=fake,
                timeout_seconds=0.05,
                paths=paths,
            )
    finally:
        os.environ.pop("SASE_FAKE_EXEC_SLEEP", None)
    assert excinfo.value.code == "timeout"
    assert Path(paths["directory"]).is_dir()


def test_remote_supports_detached_execution_reads_capability(tmp_path: Path) -> None:
    fake = FakeOpenSSHEndpoint(tmp_path)
    assert remote_supports_detached_execution("target", command_runner=fake) is True
    fake.capabilities = ()
    shim = tmp_path / "bin" / "sase"
    del shim
    fake = FakeOpenSSHEndpoint(tmp_path, capabilities=())
    assert remote_supports_detached_execution("target", command_runner=fake) is False


def test_run_remote_sudo_detached_fetches_handshake_and_leaves_files(
    tmp_path: Path,
) -> None:
    fake = FakeOpenSSHEndpoint(tmp_path)
    paths = allocate_remote_sudo_paths(base=str(tmp_path / "detach dir"))
    payload, returned = run_remote_sudo_detached(
        "target",
        _manifest(),
        manifest_sha256="abc",
        command_runner=fake,
        paths=paths,
    )
    assert payload["kind"] == "sudo_exec_started"
    assert returned == paths
    assert Path(paths["handshake"]).is_file()
    assert Path(paths["directory"]).is_dir()
    assert not any("rm -rf" in command for command in fake.joined)


def test_run_remote_sudo_detached_auth_failure_fetches_ledger_and_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_FAKE_LEDGER_OUTCOME", "auth_failed")
    fake = FakeOpenSSHEndpoint(tmp_path)
    paths = allocate_remote_sudo_paths(base=str(tmp_path / "auth"))
    payload, _returned = run_remote_sudo_detached(
        "target",
        _manifest(),
        manifest_sha256="abc",
        command_runner=fake,
        paths=paths,
    )
    assert payload["outcome"] == "auth_failed"
    assert not Path(paths["directory"]).exists()


def test_staging_mkdir_failure_is_atomic(tmp_path: Path) -> None:
    fake = FakeOpenSSHEndpoint(tmp_path)
    blocked = tmp_path / "blocked"
    blocked.write_text("not-a-directory\n", encoding="utf-8")
    paths = allocate_remote_sudo_paths(base=str(blocked))
    with pytest.raises(GateError) as excinfo:
        run_remote_sudo(
            "target",
            _manifest(),
            manifest_sha256="abc",
            command_runner=fake,
            paths=paths,
        )
    assert excinfo.value.code == "remote_sudo_stage_failed"
    assert "directory" in str(excinfo.value)
    assert not any("sase sudo exec --manifest" in command for command in fake.joined)


def test_probe_remote_executor_liveness_uses_proc_not_signals(tmp_path: Path) -> None:
    pid = os.getpid()
    identity = current_process_identity(pid)
    fake = FakeOpenSSHEndpoint(tmp_path)
    live = _probe_remote_executor_liveness(
        "target",
        {"executor_pid": pid, "executor_identity": identity},
        command_runner=fake,
    )
    assert live.classification == "live"
    assert all("kill" not in command for command in fake.joined)
    mismatch = _probe_remote_executor_liveness(
        "target",
        {"executor_pid": pid, "executor_identity": "other-boot:1"},
        command_runner=fake,
    )
    assert mismatch.classification == "dead"
    missing = _probe_remote_executor_liveness(
        "target",
        {"executor_pid": 999_999_999, "executor_identity": identity},
        command_runner=fake,
    )
    assert missing.classification == "dead"


def test_probe_remote_executor_liveness_permission_is_unknown(tmp_path: Path) -> None:
    fake = FakeOpenSSHEndpoint(tmp_path)
    fake.liveness_exit = 2
    result = _probe_remote_executor_liveness(
        "target",
        {"executor_pid": os.getpid(), "executor_identity": "boot:1"},
        command_runner=fake,
    )
    assert result.classification == "unknown"


def test_wait_for_remote_sudo_ledger_streams_output_without_duplication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.sudo.ssh._REMOTE_POLL_SECONDS", 0.0)
    paths = allocate_remote_sudo_paths(base=str(tmp_path / "stream"))
    Path(paths["directory"]).mkdir(parents=True)
    log_path = Path(paths["log"])
    log_path.write_bytes(b"starting reviewed command\n")
    dest = BytesIO()
    polls = {"n": 0}
    inner = FakeOpenSSHEndpoint(tmp_path)

    def runner(argv: list[str], **kwargs: Any) -> Any:
        polls["n"] += 1
        if polls["n"] == 3:
            log_path.write_bytes(b"starting reviewed command\ndone\n")
            Path(paths["ledger"]).write_text(
                '{"schema_version":1,"request_id":"sudo-1",'
                '"manifest_sha256":"abc","outcome":"completed",'
                '"entries":[],"diagnostic":null}\n',
                encoding="utf-8",
            )
        return inner(argv, **kwargs)

    ledger = wait_for_remote_sudo_ledger(
        "target",
        paths,
        handshake={
            "executor_pid": os.getpid(),
            "executor_identity": current_process_identity(os.getpid()),
        },
        command_runner=runner,
        timeout_seconds=1.0,
        dest=dest,
    )
    assert ledger["outcome"] == "completed"
    assert dest.getvalue() == b"starting reviewed command\ndone\n"


def test_wait_for_remote_sudo_ledger_stop_writes_remote_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.sudo.ssh._REMOTE_POLL_SECONDS", 0.0)
    monkeypatch.setattr("sase.sudo.ssh._REMOTE_STOP_GRACE_SECONDS", 0.01)
    paths = allocate_remote_sudo_paths(base=str(tmp_path / "stop"))
    Path(paths["directory"]).mkdir(parents=True)
    inner = FakeOpenSSHEndpoint(tmp_path)
    polls = {"n": 0}

    def runner(argv: list[str], **kwargs: Any) -> Any:
        polls["n"] += 1
        if polls["n"] == 1:
            os.kill(os.getpid(), signal.SIGTERM)
        return inner(argv, **kwargs)

    with pytest.raises(GateError) as excinfo:
        wait_for_remote_sudo_ledger(
            "target",
            paths,
            handshake={
                "executor_pid": os.getpid(),
                "executor_identity": current_process_identity(os.getpid()),
            },
            command_runner=runner,
            timeout_seconds=1.0,
            dest=BytesIO(),
        )
    assert excinfo.value.code == "killed"
    assert Path(paths["stop"]).is_file()


def test_wait_for_remote_sudo_ledger_unreachable_keeps_offset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.sudo.ssh._REMOTE_POLL_SECONDS", 0.0)
    paths = allocate_remote_sudo_paths(base=str(tmp_path / "net"))
    Path(paths["directory"]).mkdir(parents=True)
    Path(paths["log"]).write_bytes(b"one\n")
    dest = BytesIO()
    inner = FakeOpenSSHEndpoint(tmp_path)
    inner.fail_after_calls = 2

    def runner(argv: list[str], **kwargs: Any) -> Any:
        completed = inner(argv, **kwargs)
        if len(inner.calls) == 6:
            Path(paths["ledger"]).write_text(
                '{"schema_version":1,"request_id":"sudo-1",'
                '"manifest_sha256":"abc","outcome":"completed",'
                '"entries":[],"diagnostic":null}\n',
                encoding="utf-8",
            )
            inner.fail_after_calls = None
            inner.unreachable = False
        return completed

    with pytest.raises(GateError) as excinfo:
        wait_for_remote_sudo_ledger(
            "target",
            paths,
            handshake={
                "executor_pid": os.getpid(),
                "executor_identity": current_process_identity(os.getpid()),
            },
            command_runner=runner,
            timeout_seconds=0.05,
            dest=dest,
        )
    assert excinfo.value.code == "timeout"
    assert Path(paths["directory"]).is_dir()


def test_network_loss_after_spawn_retains_remote_paths(tmp_path: Path) -> None:
    fake = FakeOpenSSHEndpoint(tmp_path)
    fake.fail_after_calls = 3
    paths = allocate_remote_sudo_paths(base=str(tmp_path / "lost"))
    with pytest.raises(GateError) as excinfo:
        run_remote_sudo_detached(
            "target",
            _manifest(),
            manifest_sha256="abc",
            command_runner=fake,
            paths=paths,
        )
    assert excinfo.value.code in {
        "remote_sudo_startup_unresolved",
        "remote_sudo_exec_failed",
        "timeout",
    }
    assert Path(paths["directory"]).exists()


def test_cleanup_remote_sudo_retries_then_succeeds(tmp_path: Path) -> None:
    paths = allocate_remote_sudo_paths(base=str(tmp_path / "retry"))
    Path(paths["directory"]).mkdir(parents=True)
    Path(paths["manifest"]).write_text("{}\n", encoding="utf-8")
    inner = FakeOpenSSHEndpoint(tmp_path)
    attempts = {"n": 0}

    def runner(argv: list[str], **kwargs: Any) -> Any:
        attempts["n"] += 1
        if attempts["n"] == 1:
            import subprocess

            return subprocess.CompletedProcess(argv, 255, stdout=b"", stderr=b"")
        return inner(argv, **kwargs)

    assert cleanup_remote_sudo("target", paths, command_runner=runner) is True
    assert not Path(paths["directory"]).exists()


def test_detached_capability_skew_falls_back_before_staging(tmp_path: Path) -> None:
    fake = FakeOpenSSHEndpoint(tmp_path, capabilities=())
    paths = allocate_remote_sudo_paths(base=str(tmp_path / "skew"))
    with pytest.raises(GateError) as excinfo:
        run_remote_sudo_detached(
            "target",
            _manifest(),
            manifest_sha256="abc",
            command_runner=fake,
            paths=paths,
        )
    assert excinfo.value.code == "detach_unsupported"
    assert not Path(paths["directory"]).exists()
