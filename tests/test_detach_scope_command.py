"""Unit tests for ``detach_scope`` command construction and unit detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.detach_scope import (
    DETACH_SCOPE_DISABLE_ENV,
    _DetachScopeCommand,
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
    monkeypatch.setattr("sase.detach_scope._systemd_run_version", lambda _path: None)

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
        escape_reason="sase_unit",
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


def test_detach_scope_noops_outside_user_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_root = _proc_root(tmp_path, "0::/kubepods/besteffort/session-2.scope\n")
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
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
        runtime_dir=runtime_dir,
    )

    assert launch.argv == ["sase", "agent"]
    assert launch.escaped is False
    assert launch.escape_reason is None
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


def test_detach_scope_escapes_from_tmux_scope_via_user_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_root = _proc_root(
        tmp_path,
        "0::/user.slice/user-1000.slice/user@1000.service/app.slice/tmux-spawn-abc.scope\n",
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.detach_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.detach_scope.os.getpid", lambda: 123)
    monkeypatch.setattr("sase.detach_scope.os.getuid", lambda: 1000)
    monkeypatch.setattr(
        "sase.detach_scope.shutil.which",
        lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else None,
    )
    monkeypatch.setattr("sase.detach_scope._systemd_run_version", lambda _p: None)

    launch = detach_scope(
        ["sase", "agent"],
        description="SASE agent runner",
        unit_prefix="sase-agent",
        proc_root=proc_root,
        runtime_dir=runtime_dir,
    )

    assert launch.argv[:4] == [
        "/usr/bin/systemd-run",
        "--user",
        "--scope",
        "--quiet",
    ]
    assert launch.escaped is True
    assert launch.escape_reason == "user_manager"
    assert launch.parent_unit == "tmux-spawn-abc.scope"


def test_detach_scope_ignores_other_uid_user_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_root = _proc_root(
        tmp_path,
        "0::/user.slice/user-1001.slice/user@1001.service/app.slice/tmux-spawn-abc.scope\n",
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.detach_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.detach_scope.os.getpid", lambda: 123)
    monkeypatch.setattr("sase.detach_scope.os.getuid", lambda: 1000)
    monkeypatch.setattr(
        "sase.detach_scope.shutil.which",
        lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else None,
    )

    launch = detach_scope(
        ["sase", "agent"],
        description="SASE agent runner",
        unit_prefix="sase-agent",
        proc_root=proc_root,
        runtime_dir=runtime_dir,
    )

    assert launch.argv == ["sase", "agent"]
    assert launch.escaped is False
    assert launch.escape_reason is None


def test_detach_scope_escapes_via_runtime_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_root = _proc_root(tmp_path, "0::/user.slice/app.slice/session-2.scope\n")
    runtime_dir = tmp_path / "runtime"
    (runtime_dir / "systemd").mkdir(parents=True)
    (runtime_dir / "systemd" / "private").write_bytes(b"")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.detach_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.detach_scope.os.getpid", lambda: 123)
    monkeypatch.setattr(
        "sase.detach_scope.shutil.which",
        lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else None,
    )
    monkeypatch.setattr("sase.detach_scope._systemd_run_version", lambda _p: None)

    launch = detach_scope(
        ["sase", "agent"],
        description="SASE agent runner",
        unit_prefix="sase-agent",
        proc_root=proc_root,
        runtime_dir=runtime_dir,
    )

    assert launch.escaped is True
    assert launch.escape_reason == "user_manager"
    assert launch.parent_unit == "session-2.scope"


def test_detach_scope_disable_env_wins_over_user_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_root = _proc_root(
        tmp_path,
        "0::/user.slice/user-1000.slice/user@1000.service/app.slice/tmux-spawn-abc.scope\n",
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    monkeypatch.setenv(DETACH_SCOPE_DISABLE_ENV, "1")
    monkeypatch.setattr("sase.detach_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.detach_scope.os.getpid", lambda: 123)
    monkeypatch.setattr("sase.detach_scope.os.getuid", lambda: 1000)
    monkeypatch.setattr(
        "sase.detach_scope.shutil.which",
        lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else None,
    )

    launch = detach_scope(
        ["sase", "agent"],
        description="SASE agent runner",
        unit_prefix="sase-agent",
        proc_root=proc_root,
        runtime_dir=runtime_dir,
    )

    assert launch.argv == ["sase", "agent"]
    assert launch.escaped is False
    assert launch.escape_reason is None
    assert launch.parent_unit is None


@pytest.mark.parametrize(
    ("version", "expected"),
    [(255, True), (243, True), (241, False), (None, False)],
)
def test_detach_scope_oom_policy_gated_by_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: int | None,
    expected: bool,
) -> None:
    proc_root = _proc_root(tmp_path, "0::/user.slice/app.slice/sase.service\n")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.detach_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.detach_scope.os.getpid", lambda: 123)
    monkeypatch.setattr(
        "sase.detach_scope.shutil.which",
        lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else None,
    )
    monkeypatch.setattr("sase.detach_scope._systemd_run_version", lambda _p: version)

    launch = detach_scope(
        ["sase", "agent"],
        description="SASE agent runner",
        unit_prefix="sase-agent",
        proc_root=proc_root,
    )

    assert ("--property=OOMPolicy=continue" in launch.argv) is expected


def test_systemd_run_version_parses_first_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess as _subprocess

    from sase.detach_scope import _systemd_run_version

    def _run(stdout: str, returncode: int = 0):
        def _fake(*_args: object, **_kwargs: object) -> object:
            return _subprocess.CompletedProcess(
                args=["systemd-run", "--version"],
                returncode=returncode,
                stdout=stdout,
                stderr="",
            )

        return _fake

    _systemd_run_version.cache_clear()
    monkeypatch.setattr(
        "sase.detach_scope.subprocess.run", _run("systemd 255 (255.4-1ubuntu3)\n")
    )
    assert _systemd_run_version("/fake/run-255") == 255

    _systemd_run_version.cache_clear()
    monkeypatch.setattr(
        "sase.detach_scope.subprocess.run", _run("not systemd at all\n")
    )
    assert _systemd_run_version("/fake/run-bogus") is None

    _systemd_run_version.cache_clear()
    monkeypatch.setattr("sase.detach_scope.subprocess.run", _run("", returncode=1))
    assert _systemd_run_version("/fake/run-fail") is None
    _systemd_run_version.cache_clear()


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
