"""Coverage for external sudo runner invocation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.notification_gates.models import GateError
from sase.sudo import runner as sudo_runner


def _write_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)


def test_sudo_runner_resolves_from_python_environment_before_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_bin = tmp_path / "venv" / "bin"
    path_bin = tmp_path / "path"
    venv_bin.mkdir(parents=True)
    path_bin.mkdir()
    venv_runner = venv_bin / "sase_sudo_runner"
    path_runner = path_bin / "sase_sudo_runner"
    _write_executable(venv_runner)
    _write_executable(path_runner)
    monkeypatch.setattr(sudo_runner.sys, "executable", str(venv_bin / "python"))
    monkeypatch.setattr(sudo_runner.shutil, "which", lambda _name: str(path_runner))
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(
        argv: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), dict(kwargs)))
        return subprocess.CompletedProcess(argv, 0, stdout='{"ok": true}\n')

    monkeypatch.setattr(sudo_runner.subprocess, "run", fake_run)

    result = sudo_runner.run_sudo_runner_file(
        tmp_path / "manifest.json",
        manifest_sha256="abc123",
    )

    assert result == {"ok": True}
    assert calls[0][0][:5] == [
        str(venv_runner),
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--expected-sha256",
        "abc123",
    ]


def test_sudo_runner_falls_back_to_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_bin = tmp_path / "venv" / "bin"
    path_bin = tmp_path / "path"
    venv_bin.mkdir(parents=True)
    path_bin.mkdir()
    path_runner = path_bin / "sase_sudo_runner"
    _write_executable(path_runner)
    monkeypatch.setattr(sudo_runner.sys, "executable", str(venv_bin / "python"))
    monkeypatch.setattr(sudo_runner.shutil, "which", lambda _name: str(path_runner))
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout='{"ok": true}\n')

    monkeypatch.setattr(sudo_runner.subprocess, "run", fake_run)

    result = sudo_runner.run_sudo_runner_file(
        tmp_path / "manifest.json",
        manifest_sha256="abc123",
    )

    assert result == {"ok": True}
    assert calls[0][0] == str(path_runner)


def test_sudo_runner_unavailable_names_checked_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    monkeypatch.setattr(sudo_runner.sys, "executable", str(venv_bin / "python"))
    monkeypatch.setattr(sudo_runner.shutil, "which", lambda _name: None)

    with pytest.raises(GateError) as excinfo:
        sudo_runner.run_sudo_runner_file(
            tmp_path / "manifest.json",
            manifest_sha256="abc123",
        )

    assert excinfo.value.code == "runner_unavailable"
    assert excinfo.value.target == "sase_sudo_runner"
    assert str(venv_bin / "sase_sudo_runner") in str(excinfo.value)
    assert "PATH" in str(excinfo.value)


def test_sudo_runner_probe_parses_detached_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    runner = venv_bin / "sase_sudo_runner"
    runner.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' "
        '\'{"schema_version":1,"capabilities":["detached_execution"]}\'\n',
        encoding="utf-8",
    )
    runner.chmod(0o755)
    monkeypatch.setattr(sudo_runner.sys, "executable", str(venv_bin / "python"))
    monkeypatch.setattr(sudo_runner.shutil, "which", lambda _name: None)

    assert sudo_runner.runner_supports_detached_execution() is True


def test_sudo_runner_probe_treats_unknown_output_as_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    runner = venv_bin / "sase_sudo_runner"
    runner.write_text("#!/bin/sh\necho usage >&2\nexit 2\n", encoding="utf-8")
    runner.chmod(0o755)
    monkeypatch.setattr(sudo_runner.sys, "executable", str(venv_bin / "python"))
    monkeypatch.setattr(sudo_runner.shutil, "which", lambda _name: None)

    assert sudo_runner.runner_supports_detached_execution() is False


def test_sudo_runner_detached_passes_detach_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    runner = venv_bin / "sase_sudo_runner"
    _write_executable(runner)
    monkeypatch.setattr(sudo_runner.sys, "executable", str(venv_bin / "python"))
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='{"kind":"sudo_exec_started","executor_pid":7}\n',
        )

    monkeypatch.setattr(sudo_runner.subprocess, "run", fake_run)
    detach_dir = tmp_path / "exec"
    detach_dir.mkdir()

    result = sudo_runner.run_sudo_runner_detached(
        tmp_path / "manifest.json",
        manifest_sha256="abc123",
        detach_dir=detach_dir,
    )

    assert result == {"kind": "sudo_exec_started", "executor_pid": 7}
    assert calls[0] == [
        str(runner),
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--expected-sha256",
        "abc123",
        "--detach-dir",
        str(detach_dir),
    ]


def test_sudo_runner_detached_returns_auth_failure_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    runner = venv_bin / "sase_sudo_runner"
    _write_executable(runner)
    monkeypatch.setattr(sudo_runner.sys, "executable", str(venv_bin / "python"))

    def fake_run(
        argv: list[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            10,
            stdout='{"outcome":"auth_failed","entries":[]}\n',
        )

    monkeypatch.setattr(sudo_runner.subprocess, "run", fake_run)

    result = sudo_runner.run_sudo_runner_detached(
        tmp_path / "manifest.json",
        manifest_sha256="abc123",
        detach_dir=tmp_path / "exec",
    )

    assert result == {"outcome": "auth_failed", "entries": []}
