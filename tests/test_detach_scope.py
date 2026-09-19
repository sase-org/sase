"""Tests for escaping service-owned cgroups when launching detached work."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sase.detach_scope import (
    DETACH_SCOPE_DISABLE_ENV,
    _DetachScopeCommand,
    _current_systemd_unit,
    _is_sase_owned_systemd_unit,
    _process_systemd_unit,
    detach_scope,
)


def _proc_root(tmp_path: Path, cgroup: str) -> Path:
    proc_root = tmp_path / "proc"
    process_dir = proc_root / "123"
    process_dir.mkdir(parents=True)
    (process_dir / "cgroup").write_text(cgroup, encoding="utf-8")
    return proc_root


def test_process_systemd_unit_parses_scope_and_service(tmp_path: Path) -> None:
    scope_root = _proc_root(
        tmp_path / "scope",
        "0::/user.slice/user-1000.slice/user@1000.service/app.slice/sase-axe-1.scope\n",
    )
    service_root = _proc_root(
        tmp_path / "service",
        "0::/user.slice/user-1000.slice/user@1000.service/app.slice/sase.service\n",
    )

    assert _process_systemd_unit(123, proc_root=scope_root) == "sase-axe-1.scope"
    assert _process_systemd_unit(123, proc_root=service_root) == "sase.service"


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("sase.service", True),
        ("sase-axe-123.scope", True),
        ("sase-proc-123.scope", True),
        ("sase-host.service", True),
        ("session-2.scope", False),
        ("tmux-spawn-example.scope", False),
        (None, False),
    ],
)
def test_sase_owned_systemd_unit_matrix(unit: str | None, expected: bool) -> None:
    assert _is_sase_owned_systemd_unit(unit) is expected


def test_detach_scope_wraps_inside_sase_cgroup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_root = _proc_root(tmp_path, "0::/user.slice/app.slice/sase.service\n")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.detach_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.detach_scope.os.getpid", lambda: 123)
    monkeypatch.setattr("sase.detach_scope.time.time_ns", lambda: 456)
    monkeypatch.setattr(
        "sase.detach_scope.shutil.which",
        lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else None,
    )

    launch = detach_scope(
        ["/usr/bin/sase", "agent"],
        description="SASE agent runner",
        unit_prefix="sase-agent",
        proc_root=proc_root,
    )

    assert launch == _DetachScopeCommand(
        [
            "/usr/bin/systemd-run",
            "--user",
            "--scope",
            "--quiet",
            "--collect",
            "--unit=sase-agent-123-456",
            "--description=SASE agent runner",
            "--",
            "/usr/bin/sase",
            "agent",
        ],
        start_new_session=True,
        escaped=True,
        method="systemd-run",
        parent_unit="sase.service",
    )


def test_detach_scope_noops_without_systemd_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_root = _proc_root(tmp_path, "0::/user.slice/app.slice/sase.service\n")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.detach_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.detach_scope.os.getpid", lambda: 123)
    monkeypatch.setattr("sase.detach_scope.shutil.which", lambda _name: None)

    launch = detach_scope(
        ["sase", "agent"],
        description="SASE agent runner",
        unit_prefix="sase-agent",
        proc_root=proc_root,
    )

    assert launch.argv == ["sase", "agent"]
    assert launch.escaped is False
    assert launch.parent_unit == "sase.service"


def test_detach_scope_noops_outside_sase_cgroup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_root = _proc_root(tmp_path, "0::/user.slice/app.slice/session-2.scope\n")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.detach_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.detach_scope.os.getpid", lambda: 123)
    monkeypatch.setattr(
        "sase.detach_scope.shutil.which",
        lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else None,
    )

    launch = detach_scope(
        ["sase", "agent"],
        description="SASE agent runner",
        unit_prefix="sase-agent",
        proc_root=proc_root,
    )

    assert launch.argv == ["sase", "agent"]
    assert launch.escaped is False
    assert launch.parent_unit == "session-2.scope"


def test_detach_scope_honors_disable_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_root = _proc_root(tmp_path, "0::/user.slice/app.slice/sase.service\n")
    monkeypatch.setenv(DETACH_SCOPE_DISABLE_ENV, "1")
    monkeypatch.setattr("sase.detach_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.detach_scope.os.getpid", lambda: 123)
    monkeypatch.setattr(
        "sase.detach_scope.shutil.which",
        lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else None,
    )

    launch = detach_scope(
        ["sase", "agent"],
        description="SASE agent runner",
        unit_prefix="sase-agent",
        proc_root=proc_root,
    )

    assert launch.argv == ["sase", "agent"]
    assert launch.escaped is False
    assert launch.parent_unit is None


def test_detach_scope_uses_setsid_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.detach_scope.sys.platform", "darwin")

    launch = detach_scope(
        ["sase", "agent"],
        description="SASE agent runner",
        unit_prefix="sase-agent",
        start_new_session=False,
    )

    assert launch.argv == ["sase", "agent"]
    assert launch.start_new_session is True
    assert launch.escaped is True
    assert launch.method == "setsid"


def test_live_systemd_scope_changes_child_cgroup_when_running_from_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "linux":
        pytest.skip("Linux-only cgroup regression")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    parent_unit = _current_systemd_unit()
    if not _is_sase_owned_systemd_unit(parent_unit):
        pytest.skip("test process is not running inside a SASE-owned systemd unit")
    if shutil.which("systemd-run") is None:
        pytest.skip("systemd-run is unavailable")

    parent_cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
    launch = detach_scope(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; print(Path('/proc/self/cgroup').read_text())",
        ],
        description="SASE detach-scope regression",
        unit_prefix="sase-detach-test",
    )
    if not launch.escaped:
        pytest.skip("detach_scope did not escape in this environment")

    result = subprocess.run(
        launch.argv,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"systemd-run failed: {result.stderr.strip()}")

    assert result.stdout.strip()
    assert result.stdout != parent_cgroup


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
