"""Focused runtime tests for the Python service host."""

from __future__ import annotations

import dataclasses
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.procs import read_procs, reserve_proc
from sase.procs.service_meta import (
    SERVICE_HOST_ORIGIN,
    SERVICE_ONESHOT_ORIGIN,
    SERVICE_PROC_MODE_DAEMON,
)
from sase.service.config import (
    ServiceConfigComposition,
    ServiceEnablementSource,
    ServiceLauncher,
    ServiceProcConfig,
)
from sase.service.host import _entry_launch, _ServiceHost
from sase.service.paths import service_proc_output_log_path
from sase.service.state import read_service_state


def _entry_argv(entry: ServiceProcConfig) -> tuple[str, ...]:
    return _entry_launch(entry).argv


def _service_entry(
    *,
    launcher: ServiceLauncher,
    name: str = "demo",
    source: str = "user",
) -> ServiceProcConfig:
    return ServiceProcConfig(
        name=name,
        available=True,
        source=source,
        declared_by="pytest",
        enabled=True,
        enablement=ServiceEnablementSource(explicit=True, layer="pytest"),
        mode="daemon",
        restart="on-failure",
        stop_signal="SIGTERM",
        stop_timeout_seconds=1.0,
        log_max_bytes=1024,
        launcher=launcher,
        success_exit_codes=(0,),
    )


def test_service_host_launches_direct_child_and_settles_durable_row(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    entry = _service_entry(
        launcher=ServiceLauncher(
            kind="command",
            command=[sys.executable, "-c", "print('service child', flush=True)"],
            argv=(sys.executable, "-c", "print('service child', flush=True)"),
        ),
    )
    config = ServiceConfigComposition(
        schema_version=1,
        fatal=False,
        procs=(entry,),
        diagnostics=(),
        ignored_layers=(),
    )
    host = _ServiceHost()

    host._launch(entry, history=None)
    running = host._children["demo"]
    running.process.wait(timeout=10)
    host._observe_exits(config, read_service_state())

    rows = read_procs()
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "success"
    assert row.service is not None
    assert row.service.name == "demo"
    assert row.service.mode == SERVICE_PROC_MODE_DAEMON
    assert row.service.source == "user"
    assert "demo" not in host._children
    assert "demo" not in host._pending

    log_path = service_proc_output_log_path("demo")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and (
        not log_path.exists() or "service child" not in log_path.read_text()
    ):
        time.sleep(0.05)  # sase-test-wait: background output pump flushes log
    assert "service child" in log_path.read_text(encoding="utf-8")


def test_service_host_reserves_daemons_under_the_host_origin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    host = _ServiceHost()

    host._launch(_command_entry((sys.executable, "-c", "pass")), history=None)
    host._children["demo"].process.wait(timeout=10)

    (row,) = read_procs()
    assert row.origin == SERVICE_HOST_ORIGIN == "service-host"
    assert SERVICE_ONESHOT_ORIGIN == "service-proc"


def test_service_host_warns_once_when_the_store_drops_the_service_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))

    def _reserve_without_marker(*args, **kwargs):
        # Model a stale sase_core_rs build: the row is stored but the additive
        # ``service`` field never makes the round trip.
        outcome = reserve_proc(*args, **kwargs)
        stripped = dataclasses.replace(outcome.proc, service=None)
        return dataclasses.replace(outcome, proc=stripped)

    monkeypatch.setattr("sase.service.host.reserve_proc", _reserve_without_marker)
    host = _ServiceHost()
    long_running = (sys.executable, "-c", "import time; time.sleep(30)")
    first = dataclasses.replace(_command_entry(long_running), name="first")
    second = dataclasses.replace(_command_entry(long_running), name="second")

    try:
        host._launch(first, history=None)
        host._launch(second, history=None)

        # The launch is never refused, and the supervisor claim still lands.
        assert set(host._children) == {"first", "second"}
        claimed = {row.proc_id: row.supervisor_id for row in read_procs()}
        assert claimed == {
            running.proc_id: running.supervisor_id
            for running in host._children.values()
        }
    finally:
        for running in host._children.values():
            running.process.kill()
            running.process.wait(timeout=10)

    warning = capsys.readouterr().err
    assert warning.count("dropped the service marker") == 1
    assert "sase_core_rs" in warning
    assert "sase-core" in warning


def test_service_host_stays_quiet_when_the_service_marker_round_trips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    host = _ServiceHost()

    host._launch(_command_entry((sys.executable, "-c", "pass")), history=None)
    host._children["demo"].process.wait(timeout=10)

    assert "service marker" not in capsys.readouterr().err


def test_gateway_builtin_resolves_direct_gateway_argv(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.integrations.mobile_gateway.prepare_mobile_gateway_service_launch",
        lambda: SimpleNamespace(argv=["sase_gateway", "--bind", "127.0.0.1:7629"]),
    )
    entry = _service_entry(
        name="gateway",
        source="builtin",
        launcher=ServiceLauncher(kind="builtin", builtin="gateway"),
    )

    argv = _entry_argv(entry)

    assert argv == ("sase_gateway", "--bind", "127.0.0.1:7629")
    assert "mobile gateway start" not in " ".join(argv)


def test_gateway_builtin_prepare_failure_is_recorded(monkeypatch) -> None:
    def fail_prepare() -> object:
        raise RuntimeError("gateway config invalid")

    monkeypatch.setattr(
        "sase.integrations.mobile_gateway.prepare_mobile_gateway_service_launch",
        fail_prepare,
    )
    entry = _service_entry(
        name="gateway",
        source="builtin",
        launcher=ServiceLauncher(kind="builtin", builtin="gateway"),
    )
    host = _ServiceHost()

    host._launch(entry, history=None)

    assert "gateway" not in host._children
    assert host._last_exits["gateway"].spawn_error == "gateway config invalid"


def _executable(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _command_entry(argv: tuple[str, ...], *, env: dict[str, str] | None = None):
    entry = _service_entry(
        launcher=ServiceLauncher(kind="command", command=list(argv), argv=argv),
    )
    if env is not None:
        entry = dataclasses.replace(entry, env=env)
    return entry


def _isolate_launcher_lookup(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """Return an empty ``PATH`` dir and the bin dir of a fake interpreter."""
    path_dir = tmp_path / "on-path"
    path_dir.mkdir()
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    monkeypatch.setenv("PATH", str(path_dir))
    monkeypatch.setattr(sys, "executable", str(bin_dir / "python"))
    return path_dir, bin_dir


def test_entry_argv_resolves_bare_name_next_to_interpreter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _path_dir, bin_dir = _isolate_launcher_lookup(monkeypatch, tmp_path)
    script = _executable(bin_dir, "plugin_receiver")

    argv = _entry_argv(_command_entry(("plugin_receiver", "--receiver", "-v")))

    assert argv == (str(script), "--receiver", "-v")


def test_entry_argv_prefers_path_hit_over_interpreter_sibling(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path_dir, bin_dir = _isolate_launcher_lookup(monkeypatch, tmp_path)
    _executable(path_dir, "plugin_receiver")
    _executable(bin_dir, "plugin_receiver")

    argv = _entry_argv(_command_entry(("plugin_receiver", "--receiver")))

    assert argv == ("plugin_receiver", "--receiver")


def test_entry_argv_resolves_against_the_entry_path_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _path_dir, bin_dir = _isolate_launcher_lookup(monkeypatch, tmp_path)
    _executable(bin_dir, "plugin_receiver")
    own_dir = tmp_path / "entry-path"
    _executable(own_dir, "plugin_receiver")

    argv = _entry_argv(
        _command_entry(("plugin_receiver",), env={"PATH": str(own_dir)}),
    )

    assert argv == ("plugin_receiver",)


def test_entry_argv_passes_explicit_paths_through(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _path_dir, bin_dir = _isolate_launcher_lookup(monkeypatch, tmp_path)
    _executable(bin_dir, "plugin_receiver")

    argv = _entry_argv(_command_entry(("./plugin_receiver", "--receiver")))

    assert argv == ("./plugin_receiver", "--receiver")


def test_entry_argv_passes_unresolvable_bare_name_through(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_launcher_lookup(monkeypatch, tmp_path)

    argv = _entry_argv(_command_entry(("plugin_receiver", "--receiver")))

    assert argv == ("plugin_receiver", "--receiver")


def test_entry_argv_leaves_shell_string_form_alone(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _path_dir, bin_dir = _isolate_launcher_lookup(monkeypatch, tmp_path)
    _executable(bin_dir, "plugin_receiver")
    entry = _service_entry(
        launcher=ServiceLauncher(kind="command", command="plugin_receiver --receiver"),
    )

    assert _entry_argv(entry) == ("/bin/sh", "-lc", "plugin_receiver --receiver")


def test_entry_argv_leaves_builtin_scheduler_unresolved(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.service.host_support._sase_command", lambda: ("/opt/bin/sase",)
    )
    entry = _service_entry(
        name="scheduler",
        source="builtin",
        launcher=ServiceLauncher(kind="builtin", builtin="scheduler"),
    )

    assert _entry_argv(entry) == ("/opt/bin/sase", "scheduler", "run")


def test_spawn_error_for_unresolvable_bare_name_carries_diagnostic(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    _path_dir, bin_dir = _isolate_launcher_lookup(monkeypatch, tmp_path)
    entry = _command_entry(("plugin_receiver", "--receiver"))
    host = _ServiceHost()

    host._launch(entry, history=None)

    assert "demo" not in host._children
    spawn_error = host._last_exits["demo"].spawn_error
    assert spawn_error is not None
    assert "[Errno 2] No such file or directory: 'plugin_receiver'" in spawn_error
    assert "`plugin_receiver` was not found on PATH" in spawn_error
    assert str(bin_dir) in spawn_error
    assert "uv tool install" in spawn_error


def test_spawn_error_for_explicit_path_has_no_resolver_diagnostic(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    missing = tmp_path / "nope" / "plugin_receiver"
    host = _ServiceHost()

    host._launch(_command_entry((str(missing),)), history=None)

    spawn_error = host._last_exits["demo"].spawn_error
    assert spawn_error is not None
    assert "No such file or directory" in spawn_error
    assert "uv tool install" not in spawn_error
