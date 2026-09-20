"""Tests for service launcher resolution and the ``sase service init`` preflight."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.service.config import (
    ServiceConfigComposition,
    ServiceEnablementSource,
    ServiceLauncher,
    ServiceProcConfig,
)
from sase.service.executable import resolve_launcher_argv, service_launcher_warnings
from sase.service.platform import CommandResult, service_init_plan


def _no_path(_name: str) -> None:
    return None


def _interpreter(tmp_path: Path) -> tuple[str, Path]:
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    return str(bin_dir / "python"), bin_dir


def _script(directory: Path, name: str, *, mode: int = 0o755) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _proc(
    argv: tuple[str, ...],
    *,
    name: str = "receiver",
    enabled: bool = True,
    available: bool = True,
    kind: str = "command",
    env: dict[str, str] | None = None,
) -> ServiceProcConfig:
    return ServiceProcConfig(
        name=name,
        available=available,
        source="plugin",
        declared_by="pytest",
        enabled=enabled,
        enablement=ServiceEnablementSource(explicit=True, layer="pytest"),
        mode="daemon",
        restart="on-failure",
        stop_signal="SIGTERM",
        stop_timeout_seconds=1.0,
        log_max_bytes=4096,
        launcher=ServiceLauncher(kind=kind, command=list(argv), argv=argv),
        env=env or {},
    )


def test_path_hit_is_returned_unchanged_even_with_an_interpreter_sibling(
    tmp_path: Path,
) -> None:
    interpreter, bin_dir = _interpreter(tmp_path)
    _script(bin_dir, "tool")

    resolved = resolve_launcher_argv(
        ("tool", "--flag"),
        which_fn=lambda name: f"/usr/bin/{name}",
        interpreter=interpreter,
    )

    assert resolved.argv == ("tool", "--flag")
    assert resolved.diagnostic is None


def test_interpreter_sibling_replaces_only_argv0(tmp_path: Path) -> None:
    interpreter, bin_dir = _interpreter(tmp_path)
    script = _script(bin_dir, "tool")

    resolved = resolve_launcher_argv(
        ("tool", "--flag", "tool"),
        which_fn=_no_path,
        interpreter=interpreter,
    )

    assert resolved.argv == (str(script), "--flag", "tool")
    assert resolved.diagnostic is None


def test_non_executable_sibling_does_not_resolve(tmp_path: Path) -> None:
    interpreter, bin_dir = _interpreter(tmp_path)
    _script(bin_dir, "tool", mode=0o644)

    resolved = resolve_launcher_argv(
        ("tool",), which_fn=_no_path, interpreter=interpreter
    )

    assert resolved.argv == ("tool",)
    assert resolved.diagnostic is not None


def test_directory_sibling_does_not_resolve(tmp_path: Path) -> None:
    interpreter, bin_dir = _interpreter(tmp_path)
    (bin_dir / "tool").mkdir()

    resolved = resolve_launcher_argv(
        ("tool",), which_fn=_no_path, interpreter=interpreter
    )

    assert resolved.argv == ("tool",)
    assert resolved.diagnostic is not None


def test_empty_argv_is_returned_unchanged() -> None:
    def fail(_name: str) -> str | None:
        raise AssertionError("empty argv must not be looked up")

    resolved = resolve_launcher_argv((), which_fn=fail, interpreter="/x/bin/python")

    assert resolved.argv == ()
    assert resolved.diagnostic is None


def test_explicit_path_is_never_looked_up(tmp_path: Path) -> None:
    interpreter, bin_dir = _interpreter(tmp_path)
    _script(bin_dir, "tool")

    def fail(_name: str) -> str | None:
        raise AssertionError("explicit paths must not be looked up")

    for argv0 in ("./tool", "bin/tool", "/nowhere/tool"):
        resolved = resolve_launcher_argv(
            (argv0, "x"), which_fn=fail, interpreter=interpreter
        )
        assert resolved.argv == (argv0, "x")
        assert resolved.diagnostic is None


def test_unresolved_name_returns_argv_with_actionable_diagnostic(
    tmp_path: Path,
) -> None:
    interpreter, bin_dir = _interpreter(tmp_path)

    resolved = resolve_launcher_argv(
        ("sase_job_tg_inbound", "--receiver"),
        which_fn=_no_path,
        interpreter=interpreter,
    )

    assert resolved.argv == ("sase_job_tg_inbound", "--receiver")
    diagnostic = resolved.diagnostic
    assert diagnostic is not None
    assert "`sase_job_tg_inbound`" in diagnostic
    assert str(bin_dir) in diagnostic
    assert "PATH" in diagnostic
    assert "uv tool install" in diagnostic


def test_altsep_counts_as_a_path_separator(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "altsep", "\\")
    interpreter, _bin_dir = _interpreter(tmp_path)

    resolved = resolve_launcher_argv(
        ("dir\\tool",), which_fn=_no_path, interpreter=interpreter
    )

    assert resolved.argv == ("dir\\tool",)
    assert resolved.diagnostic is None


def test_launcher_warnings_cover_only_enabled_available_command_procs(
    tmp_path: Path,
) -> None:
    interpreter, bin_dir = _interpreter(tmp_path)
    _script(bin_dir, "found")
    empty = tmp_path / "empty"
    empty.mkdir()
    procs = (
        _proc(("missing",), name="broken"),
        _proc(("found",), name="resolvable"),
        _proc(("missing",), name="disabled", enabled=False),
        _proc(("missing",), name="unavailable", available=False),
        _proc(("missing",), name="builtin", kind="builtin"),
        _proc(("missing",), name="own-path", env={"PATH": "/opt/x"}),
        _proc(("/abs/missing",), name="explicit"),
    )

    warnings = service_launcher_warnings(
        {"PATH": str(empty)}, procs=procs, interpreter=interpreter
    )

    assert len(warnings) == 1
    assert warnings[0].startswith("service proc `broken` cannot start: ")
    assert "`missing`" in warnings[0]


def test_service_launcher_warnings_resolve_against_the_captured_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    interpreter, _bin_dir = _interpreter(tmp_path)
    captured = tmp_path / "captured"
    captured.mkdir()
    _script(captured, "plugin_receiver")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    procs = (_proc(("plugin_receiver",)),)

    assert (
        service_launcher_warnings(
            {"PATH": str(captured)}, procs=procs, interpreter=interpreter
        )
        == ()
    )
    assert (
        len(
            service_launcher_warnings(
                {"PATH": str(empty)}, procs=procs, interpreter=interpreter
            )
        )
        == 1
    )


def test_service_launcher_warnings_load_the_effective_service_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    interpreter, _bin_dir = _interpreter(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(
        "sase.service.executable.load_service_config",
        lambda: SimpleNamespace(procs=(_proc(("plugin_receiver",)),)),
    )

    warnings = service_launcher_warnings({"PATH": str(empty)}, interpreter=interpreter)

    assert len(warnings) == 1


def test_service_launcher_warnings_are_silent_when_config_cannot_load(
    monkeypatch,
) -> None:
    def broken() -> object:
        raise RuntimeError("bad config")

    monkeypatch.setattr("sase.service.executable.load_service_config", broken)

    assert service_launcher_warnings({"PATH": "/bin"}) == ()


class _Manager:
    """Injected platform manager: nothing installed, linger on."""

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(argv)
        if command[:3] == ("systemctl", "--user", "is-enabled"):
            return CommandResult(1, "disabled\n")
        if command[:3] == ("systemctl", "--user", "is-active"):
            return CommandResult(3, "inactive\n")
        if command[0] == "loginctl":
            return CommandResult(0, "yes\n")
        return CommandResult(0, "")


def _launcher_plan_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    procs: tuple[ServiceProcConfig, ...],
    *,
    captured_path: Path,
) -> list[str]:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    monkeypatch.setattr("sase.service.platform.readiness_warnings", lambda _env: ())
    interpreter, _bin_dir = _interpreter(tmp_path)
    monkeypatch.setattr("sase.service.executable.sys.executable", interpreter)
    monkeypatch.setattr(
        "sase.service.executable.load_service_config",
        lambda: ServiceConfigComposition(
            schema_version=1,
            fatal=False,
            procs=procs,
            diagnostics=(),
            ignored_layers=(),
        ),
    )
    sase = _script(tmp_path, "sase")
    plan = service_init_plan(
        runner=_Manager(),
        environ={"PATH": str(captured_path)},
        executable_resolver=lambda: str(sase),
    )
    return [warning for warning in plan.warnings if "cannot start" in warning]


def test_init_plan_warns_for_enabled_command_proc_that_resolves_nowhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_path = tmp_path / "captured"
    captured_path.mkdir()

    warnings = _launcher_plan_warnings(
        tmp_path,
        monkeypatch,
        (_proc(("sase_job_tg_inbound", "--receiver"), name="telegram_receiver"),),
        captured_path=captured_path,
    )

    assert len(warnings) == 1
    assert "service proc `telegram_receiver` cannot start" in warnings[0]
    assert "`sase_job_tg_inbound`" in warnings[0]
    assert "uv tool install" in warnings[0]


def test_init_plan_is_silent_for_launchers_that_resolve_disable_or_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_path = tmp_path / "captured"
    captured_path.mkdir()
    _script(captured_path, "on_path_script")
    _script(_interpreter(tmp_path)[1], "plugin_script")

    warnings = _launcher_plan_warnings(
        tmp_path,
        monkeypatch,
        (
            _proc(("on_path_script",), name="on-path"),
            _proc(("plugin_script",), name="sibling"),
            _proc(("missing",), name="disabled", enabled=False),
            _proc(("missing",), name="unavailable", available=False),
        ),
        captured_path=captured_path,
    )

    assert warnings == []
