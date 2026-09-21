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


def _escaped_launch(argv: list[str]) -> _DetachScopeCommand:
    return _DetachScopeCommand(
        ["scope", *argv],
        start_new_session=False,
        escaped=True,
        method="systemd-run",
    )


def _noop_launch(argv: list[str]) -> _DetachScopeCommand:
    return _DetachScopeCommand(list(argv), start_new_session=True)


def _fake_popen_class(captured: dict[str, object], *, pid: int = 4321) -> type:
    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: object) -> None:
            captured["popen_argv"] = list(argv)
            captured["popen_kwargs"] = kwargs
            self.pid = pid

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def poll(self) -> int | None:
            return 0

    return FakePopen


def test_crs_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _escaped_launch(list(argv))

    output_path = tmp_path / "crs.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", _fake_popen_class(captured, pid=4321)
    )
    monkeypatch.setattr(starter, "claim_next_axe_workspace", lambda *a, **k: 10)
    monkeypatch.setattr(
        starter,
        "get_workspace_directory_for_num",
        lambda *a, **k: (str(tmp_path), None),
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "run_sase_hg_clean", lambda *a, **k: (True, None))
    monkeypatch.setattr(starter, "set_comment_suffix", lambda *a, **k: None)
    monkeypatch.setattr(
        starter,
        "transfer_workspace_claim",
        lambda *a, **k: _types.SimpleNamespace(success=True, error=None),
    )
    provider = _types.SimpleNamespace(
        stash_and_clean=lambda *a, **k: (True, None),
        resolve_revision=lambda *a, **k: "rev",
        checkout=lambda *a, **k: (True, None),
    )
    monkeypatch.setattr(starter, "get_vcs_provider", lambda *a, **k: provider)
    monkeypatch.setattr(
        "sase.workspace_provider.utils.parse_workspace_dir", lambda *a: str(tmp_path)
    )
    monkeypatch.setattr("sase.vcs_provider.detect_vcs_family", lambda *a: "hg")

    patch = _types.SimpleNamespace(
        name="cl1",
        file_path="proj.sase",
        project_basename="proj",
        comments=None,
    )
    comment = _types.SimpleNamespace(reviewer="critique", file_path="")
    result = starter._start_crs_workflow(patch, comment, lambda *a: None)  # noqa: SLF001

    assert result is not None
    assert captured["detach_kwargs"] == {
        "description": "SASE CRS runner",
        "unit_prefix": "sase-crs",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_crs_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return _noop_launch(list(argv))

    output_path = tmp_path / "crs.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", _fake_popen_class(captured, pid=4321)
    )
    monkeypatch.setattr(starter, "claim_next_axe_workspace", lambda *a, **k: 10)
    monkeypatch.setattr(
        starter,
        "get_workspace_directory_for_num",
        lambda *a, **k: (str(tmp_path), None),
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "run_sase_hg_clean", lambda *a, **k: (True, None))
    monkeypatch.setattr(starter, "set_comment_suffix", lambda *a, **k: None)
    monkeypatch.setattr(
        starter,
        "transfer_workspace_claim",
        lambda *a, **k: _types.SimpleNamespace(success=True, error=None),
    )
    provider = _types.SimpleNamespace(
        stash_and_clean=lambda *a, **k: (True, None),
        resolve_revision=lambda *a, **k: "rev",
        checkout=lambda *a, **k: (True, None),
    )
    monkeypatch.setattr(starter, "get_vcs_provider", lambda *a, **k: provider)
    monkeypatch.setattr(
        "sase.workspace_provider.utils.parse_workspace_dir", lambda *a: str(tmp_path)
    )
    monkeypatch.setattr("sase.vcs_provider.detect_vcs_family", lambda *a: "hg")

    patch = _types.SimpleNamespace(
        name="cl1",
        file_path="proj.sase",
        project_basename="proj",
        comments=None,
    )
    comment = _types.SimpleNamespace(reviewer="critique", file_path="")
    result = starter._start_crs_workflow(patch, comment, lambda *a: None)  # noqa: SLF001

    assert result is not None
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_fix_hook_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _escaped_launch(list(argv))

    output_path = tmp_path / "fix.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", _fake_popen_class(captured, pid=4322)
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "get_hook_output_path", lambda *a: "")
    monkeypatch.setattr(starter, "set_hook_suffix", lambda *a, **k: None)
    monkeypatch.setattr(
        "sase.ace.hooks.try_claim_hook_for_fix", lambda *a, **k: "summary"
    )

    hook = _types.SimpleNamespace(
        command="myhook",
        display_command="myhook",
        get_status_line_for_stitch=lambda entry_id: _types.SimpleNamespace(
            timestamp="260921_120000"
        ),
    )
    patch = _types.SimpleNamespace(name="cl1", file_path="proj.sase", hooks=[])
    result = starter.start_fix_hook_workflow(patch, hook, "entry1", lambda *a: None)

    assert result is not None
    assert captured["detach_kwargs"] == {
        "description": "SASE fix-hook runner",
        "unit_prefix": "sase-fix-hook",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_fix_hook_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return _noop_launch(list(argv))

    output_path = tmp_path / "fix.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", _fake_popen_class(captured, pid=4322)
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "get_hook_output_path", lambda *a: "")
    monkeypatch.setattr(starter, "set_hook_suffix", lambda *a, **k: None)
    monkeypatch.setattr(
        "sase.ace.hooks.try_claim_hook_for_fix", lambda *a, **k: "summary"
    )

    hook = _types.SimpleNamespace(
        command="myhook",
        display_command="myhook",
        get_status_line_for_stitch=lambda entry_id: _types.SimpleNamespace(
            timestamp="260921_120000"
        ),
    )
    patch = _types.SimpleNamespace(name="cl1", file_path="proj.sase", hooks=[])
    result = starter.start_fix_hook_workflow(patch, hook, "entry1", lambda *a: None)

    assert result is not None
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_summarize_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _escaped_launch(list(argv))

    hook_output = tmp_path / "hook-out.txt"
    hook_output.write_text("boom\n")
    output_path = tmp_path / "sum.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", _fake_popen_class(captured, pid=4323)
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "get_hook_output_path", lambda *a: str(hook_output))
    monkeypatch.setattr(starter, "set_hook_suffix", lambda *a, **k: None)

    hook = _types.SimpleNamespace(
        command="myhook",
        display_command="myhook",
        get_status_line_for_stitch=lambda entry_id: _types.SimpleNamespace(
            timestamp="260921_120000"
        ),
    )
    patch = _types.SimpleNamespace(name="cl1", file_path="proj.sase", hooks=[])
    result = starter._start_summarize_hook_workflow(  # noqa: SLF001
        patch, hook, "entry1", lambda *a: None
    )

    assert result is not None
    assert captured["detach_kwargs"] == {
        "description": "SASE summarize runner",
        "unit_prefix": "sase-summarize",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_summarize_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return _noop_launch(list(argv))

    hook_output = tmp_path / "hook-out.txt"
    hook_output.write_text("boom\n")
    output_path = tmp_path / "sum.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", _fake_popen_class(captured, pid=4323)
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "get_hook_output_path", lambda *a: str(hook_output))
    monkeypatch.setattr(starter, "set_hook_suffix", lambda *a, **k: None)

    hook = _types.SimpleNamespace(
        command="myhook",
        display_command="myhook",
        get_status_line_for_stitch=lambda entry_id: _types.SimpleNamespace(
            timestamp="260921_120000"
        ),
    )
    patch = _types.SimpleNamespace(name="cl1", file_path="proj.sase", hooks=[])
    result = starter._start_summarize_hook_workflow(  # noqa: SLF001
        patch, hook, "entry1", lambda *a: None
    )

    assert result is not None
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_mentor_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.mentor_runner as mentor_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _escaped_launch(list(argv))

    output_path = tmp_path / "mentor.txt"
    monkeypatch.setattr(mentor_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        mentor_module.subprocess, "Popen", _fake_popen_class(captured, pid=4324)
    )
    monkeypatch.setattr(
        mentor_module, "_get_mentor_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(mentor_module, "set_mentor_status", lambda *a, **k: None)

    patch = _types.SimpleNamespace(name="cl1", file_path="p.sase")
    profile = _types.SimpleNamespace(profile_name="prof")
    result = mentor_module.start_single_mentor(
        patch, "entry1", profile, "m1", lambda *a: None
    )

    assert result is not None
    assert captured["detach_kwargs"] == {
        "description": "SASE mentor runner",
        "unit_prefix": "sase-mentor",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_mentor_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.mentor_runner as mentor_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return _noop_launch(list(argv))

    output_path = tmp_path / "mentor.txt"
    monkeypatch.setattr(mentor_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        mentor_module.subprocess, "Popen", _fake_popen_class(captured, pid=4324)
    )
    monkeypatch.setattr(
        mentor_module, "_get_mentor_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(mentor_module, "set_mentor_status", lambda *a, **k: None)

    patch = _types.SimpleNamespace(name="cl1", file_path="p.sase")
    profile = _types.SimpleNamespace(profile_name="prof")
    result = mentor_module.start_single_mentor(
        patch, "entry1", profile, "m1", lambda *a: None
    )

    assert result is not None
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_checks_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import sase.ace.scheduler.checks_runner as checks_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _escaped_launch(list(argv))

    monkeypatch.setattr(checks_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        checks_module.subprocess, "Popen", _fake_popen_class(captured, pid=4325)
    )
    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda *a: str(tmp_path)
    )

    output_path = tmp_path / "check.txt"
    assert (
        checks_module._start_background_check(  # noqa: SLF001
            "echo hi", str(output_path), str(tmp_path)
        )
        is True
    )
    assert captured["detach_kwargs"] == {
        "description": "SASE checks runner",
        "unit_prefix": "sase-checks",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_checks_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import sase.ace.scheduler.checks_runner as checks_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return _noop_launch(list(argv))

    monkeypatch.setattr(checks_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        checks_module.subprocess, "Popen", _fake_popen_class(captured, pid=4325)
    )
    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda *a: str(tmp_path)
    )

    output_path = tmp_path / "check.txt"
    assert (
        checks_module._start_background_check(  # noqa: SLF001
            "echo hi", str(output_path), str(tmp_path)
        )
        is True
    )
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_hook_execution_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.hooks.execution as execution_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _escaped_launch(list(argv))

    output_path = tmp_path / "hook.txt"
    monkeypatch.setattr(execution_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        execution_module.subprocess, "Popen", _fake_popen_class(captured, pid=4326)
    )
    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda *a: str(tmp_path)
    )
    monkeypatch.setattr(
        execution_module, "get_hook_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(execution_module, "generate_timestamp", lambda: "260921_120000")

    patch = _types.SimpleNamespace(name="cl1")
    hook = _types.SimpleNamespace(
        run_command="echo hi",
        display_command="echo hi",
        command="echo hi",
        status_lines=[],
    )
    updated, returned_path = execution_module.start_hook_background(
        patch, hook, str(tmp_path), "entry1"
    )

    assert returned_path == str(output_path)
    assert updated.status_lines[-1].suffix == "4326"
    assert captured["detach_kwargs"] == {
        "description": "SASE hook runner",
        "unit_prefix": "sase-hook",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_hook_execution_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.hooks.execution as execution_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return _noop_launch(list(argv))

    output_path = tmp_path / "hook.txt"
    monkeypatch.setattr(execution_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        execution_module.subprocess, "Popen", _fake_popen_class(captured, pid=4326)
    )
    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda *a: str(tmp_path)
    )
    monkeypatch.setattr(
        execution_module, "get_hook_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(execution_module, "generate_timestamp", lambda: "260921_120000")

    patch = _types.SimpleNamespace(name="cl1")
    hook = _types.SimpleNamespace(
        run_command="echo hi",
        display_command="echo hi",
        command="echo hi",
        status_lines=[],
    )
    _, returned_path = execution_module.start_hook_background(
        patch, hook, str(tmp_path), "entry1"
    )

    assert returned_path == str(output_path)
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_chat_install_worker_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.integrations import chat_install as chat_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return _escaped_launch(list(argv))

    state_dir = tmp_path / "chat_install"
    monkeypatch.setattr(chat_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(chat_module, "_STATE_DIR", state_dir)
    monkeypatch.setattr(chat_module, "_LOCK_PATH", state_dir / "install.lock")
    monkeypatch.setattr(chat_module, "_LOG_DIR", state_dir / "logs")
    monkeypatch.setattr(chat_module, "_COMPLETIONS_DIR", state_dir / "completions")
    monkeypatch.setattr(chat_module, "_JOBS_DIR", state_dir / "jobs")
    monkeypatch.setattr(
        chat_module.subprocess,
        "Popen",
        _fake_popen_class(captured, pid=4327),
    )

    result = chat_module.start_chat_install_worker()

    assert result.status == "launched"
    assert result.pid == 4327
    assert captured["detach_kwargs"] == {
        "description": "SASE chat-install worker",
        "unit_prefix": "sase-chat-install",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False
    assert popen_kwargs["pass_fds"]
    assert popen_kwargs["env"][chat_module._LOCK_FD_ENV] == str(  # noqa: SLF001
        popen_kwargs["pass_fds"][0]
    )


def test_chat_install_worker_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.integrations import chat_install as chat_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return _noop_launch(list(argv))

    state_dir = tmp_path / "chat_install"
    monkeypatch.setattr(chat_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(chat_module, "_STATE_DIR", state_dir)
    monkeypatch.setattr(chat_module, "_LOCK_PATH", state_dir / "install.lock")
    monkeypatch.setattr(chat_module, "_LOG_DIR", state_dir / "logs")
    monkeypatch.setattr(chat_module, "_COMPLETIONS_DIR", state_dir / "completions")
    monkeypatch.setattr(chat_module, "_JOBS_DIR", state_dir / "jobs")
    monkeypatch.setattr(
        chat_module.subprocess,
        "Popen",
        _fake_popen_class(captured, pid=4327),
    )

    result = chat_module.start_chat_install_worker()

    assert result.status == "launched"
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True
    assert popen_kwargs["pass_fds"]


def test_live_scope_pid_unchanged_through_detach(
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

    launch = detach_scope(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        description="SASE detach-scope pid regression",
        unit_prefix="sase-detach-pid-test",
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

    reported = result.stdout.strip().splitlines()[-1]
    assert reported.isdigit()


def test_live_scope_preserves_lock_fd_through_detach(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import os as _os

    if sys.platform != "linux":
        pytest.skip("Linux-only cgroup regression")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    parent_unit = _current_systemd_unit()
    if not _is_sase_owned_systemd_unit(parent_unit):
        pytest.skip("test process is not running inside a SASE-owned systemd unit")
    if shutil.which("systemd-run") is None:
        pytest.skip("systemd-run is unavailable")

    lock_path = tmp_path / "install.lock"
    lock_path.write_bytes(b"x")
    lock_fd = _os.open(lock_path, _os.O_RDWR)
    try:
        import fcntl as _fcntl

        _fcntl.flock(lock_fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        probe = tmp_path / "fd_probe.py"
        probe.write_text(
            "import fcntl, os, sys\n"
            "fd = int(sys.argv[1])\n"
            "st = os.fstat(fd)\n"
            "target = os.stat(sys.argv[2])\n"
            "assert (st.st_dev, st.st_ino) == (target.st_dev, target.st_ino)\n"
            "probe2 = os.open(sys.argv[2], os.O_RDWR)\n"
            "try:\n"
            "    fcntl.flock(probe2, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "except BlockingIOError:\n"
            "    print('lock-held')\n"
            "else:\n"
            "    raise SystemExit('lock fd did not survive systemd-run exec')\n",
            encoding="utf-8",
        )
        launch = detach_scope(
            [sys.executable, str(probe), str(lock_fd), str(lock_path)],
            description="SASE detach-scope lock-fd regression",
            unit_prefix="sase-detach-lock-test",
        )
        if not launch.escaped:
            pytest.skip("detach_scope did not escape in this environment")
        result = subprocess.run(
            launch.argv,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            pass_fds=(lock_fd,),
        )
        if result.returncode != 0:
            pytest.skip(f"systemd-run failed: {result.stderr.strip()}")
        assert "lock-held" in result.stdout
    finally:
        try:
            import fcntl as _fcntl2

            _fcntl2.flock(lock_fd, _fcntl2.LOCK_UN)
        except OSError:
            pass
        _os.close(lock_fd)
