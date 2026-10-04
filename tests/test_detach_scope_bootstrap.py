"""Proc and monitor supervisor bootstrap wraps children with ``detach_scope``."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.detach_scope import _DetachScopeCommand


def test_proc_supervisor_bootstrap_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import sase.procs.spawn as spawn_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _DetachScopeCommand(["scope", *argv], start_new_session=False)

    class FakePopen:
        def poll(self) -> int:
            return 0

    def fake_popen(argv: list[str], **kwargs: object) -> FakePopen:
        captured["popen_argv"] = list(argv)
        captured["popen_kwargs"] = kwargs
        return FakePopen()

    monkeypatch.setattr(spawn_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        spawn_module,
        "_supervisor_pid_file",
        lambda _proc_id: tmp_path / "proc.pid.json",
    )
    monkeypatch.setattr(spawn_module, "_read_supervisor_pid", lambda *_args: 2468)
    monkeypatch.setattr(spawn_module, "_wait_for_bootstrap_exit", lambda *_args: None)

    supervisor = spawn_module._spawn_bootstrap(  # noqa: SLF001
        "proc123",
        env={},
        stdout=subprocess.DEVNULL,
    )

    assert supervisor.pid == 2468
    assert captured["detach_kwargs"] == {
        "description": "SASE proc supervisor",
        "unit_prefix": "sase-proc",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False
    assert popen_kwargs["pass_fds"]


def test_proc_supervisor_bootstrap_uses_pid_file_for_systemd_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import sase.procs.spawn as spawn_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _DetachScopeCommand(
            ["scope", *argv],
            start_new_session=False,
            escaped=True,
            method="systemd-run",
        )

    class FakePopen:
        def poll(self) -> int:
            return 0

    def fake_popen(argv: list[str], **kwargs: object) -> FakePopen:
        captured["popen_argv"] = list(argv)
        captured["popen_kwargs"] = kwargs
        return FakePopen()

    pid_file = tmp_path / "proc.pid.json"
    monkeypatch.setattr(spawn_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(spawn_module, "_supervisor_pid_file", lambda _proc_id: pid_file)
    monkeypatch.setattr(
        spawn_module,
        "_read_supervisor_pid_file",
        lambda path, _launcher: 1357 if path == pid_file else 0,
    )
    monkeypatch.setattr(spawn_module, "_wait_for_bootstrap_exit", lambda *_args: None)

    supervisor = spawn_module._spawn_bootstrap(  # noqa: SLF001
        "proc123",
        env={},
        stdout=subprocess.DEVNULL,
    )

    assert supervisor.pid == 1357
    detach_argv = captured["detach_argv"]
    assert isinstance(detach_argv, list)
    assert "--pid-file" in detach_argv
    assert "--pid-fd" not in detach_argv
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["pass_fds"] == ()


def test_monitor_supervisor_bootstrap_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import sase.monitor.spawn as spawn_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _DetachScopeCommand(["scope", *argv], start_new_session=False)

    class FakePopen:
        def poll(self) -> int:
            return 0

    def fake_popen(argv: list[str], **kwargs: object) -> FakePopen:
        captured["popen_argv"] = list(argv)
        captured["popen_kwargs"] = kwargs
        return FakePopen()

    monkeypatch.setattr(spawn_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        spawn_module,
        "_supervisor_pid_file",
        lambda _artifacts_dir: tmp_path / "monitor.pid.json",
    )
    monkeypatch.setattr(spawn_module, "_read_supervisor_pid", lambda *_args: 2468)
    monkeypatch.setattr(spawn_module, "_wait_for_bootstrap_exit", lambda *_args: None)

    supervisor = spawn_module._spawn_bootstrap(  # noqa: SLF001
        "/tmp/artifacts",
        env={},
        stdout=subprocess.DEVNULL,
    )

    assert supervisor.pid == 2468
    assert captured["detach_kwargs"] == {
        "description": "SASE monitor supervisor",
        "unit_prefix": "sase-monitor",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False
    assert popen_kwargs["pass_fds"]


def test_monitor_supervisor_bootstrap_uses_pid_file_for_systemd_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import sase.monitor.spawn as spawn_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _DetachScopeCommand(
            ["scope", *argv],
            start_new_session=False,
            escaped=True,
            method="systemd-run",
        )

    class FakePopen:
        def poll(self) -> int:
            return 0

    def fake_popen(argv: list[str], **kwargs: object) -> FakePopen:
        captured["popen_argv"] = list(argv)
        captured["popen_kwargs"] = kwargs
        return FakePopen()

    pid_file = tmp_path / "monitor.pid.json"
    monkeypatch.setattr(spawn_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        spawn_module,
        "_supervisor_pid_file",
        lambda _artifacts_dir: pid_file,
    )
    monkeypatch.setattr(
        spawn_module,
        "_read_supervisor_pid_file",
        lambda path, _launcher: 1357 if path == pid_file else 0,
    )
    monkeypatch.setattr(spawn_module, "_wait_for_bootstrap_exit", lambda *_args: None)

    supervisor = spawn_module._spawn_bootstrap(  # noqa: SLF001
        "/tmp/artifacts",
        env={},
        stdout=subprocess.DEVNULL,
    )

    assert supervisor.pid == 1357
    detach_argv = captured["detach_argv"]
    assert isinstance(detach_argv, list)
    assert "--pid-file" in detach_argv
    assert "--pid-fd" not in detach_argv
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["pass_fds"] == ()
