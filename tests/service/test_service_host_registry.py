"""Account-wide service-host registry: register, release, stale, refuse, status."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.core.process_identity import process_identity_token
from sase.main.service_handler import _handle_service_command
from sase.service.control import _is_service_host_lock_held
from sase.service.host import _ServiceHost
from sase.service.host_lifecycle import run_host
from sase.service.host_registry import (
    SERVICE_ALLOW_SECOND_HOST_ENV,
    _ServiceHostRegistryEntry,
    _live_service_hosts,
    other_service_hosts,
    register_service_host,
    _service_host_registry_dir,
)
from sase.service.platform_models import CommandResult
from sase.service.state import read_service_state
from tests.service.service_host_scenario_helpers import (
    _compose,
    _preserved_host_globals,
    _wait_for,
)


@pytest.fixture
def registry() -> Path:
    return _service_host_registry_dir()


@pytest.fixture
def foreign_host(registry: Path, tmp_path: Path) -> Iterator[_ServiceHostRegistryEntry]:
    """A live host for another SASE home: a real process plus a held flock."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    registry.mkdir(parents=True, exist_ok=True)
    entry = _ServiceHostRegistryEntry(
        pid=child.pid,
        identity=process_identity_token(child.pid),
        sase_home=str(tmp_path / "throwaway-home" / ".sase"),
        unit=f"sase-service-{child.pid}-1.scope",
        agent_name="sase-1t3.7.1.land",
        registered_at=1.0,
    )
    path = registry / f"host-{child.pid}-1.json"
    path.write_text(json.dumps(entry.to_wire()), encoding="utf-8")
    fd = os.open(path, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield entry
    finally:
        os.close(fd)
        child.kill()
        child.wait(timeout=10)


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    return child.pid


def test_registry_dir_prefers_override_then_xdg_runtime(tmp_path: Path) -> None:
    assert (
        _service_host_registry_dir(
            {"SASE_SERVICE_HOST_REGISTRY_DIR": str(tmp_path / "r")}
        )
        == tmp_path / "r"
    )
    assert _service_host_registry_dir({"XDG_RUNTIME_DIR": str(tmp_path)}) == (
        tmp_path / "sase" / "service-hosts"
    )


def test_register_writes_a_locked_entry_and_release_removes_it(
    registry: Path, tmp_path: Path
) -> None:
    result = register_service_host(
        home=tmp_path / ".sase", unit="sase.service", agent_name="agent-a"
    )

    assert result.refused is False
    assert result.registration is not None
    hosts = _live_service_hosts()
    assert [(h.pid, h.sase_home, h.unit, h.agent_name) for h in hosts] == [
        (os.getpid(), str(tmp_path / ".sase"), "sase.service", "agent-a")
    ]
    assert hosts[0].identity == process_identity_token(os.getpid())
    assert oct(registry.stat().st_mode & 0o777) == oct(0o700)

    result.registration.release()

    assert _live_service_hosts() == []
    assert list(registry.glob("host-*.json")) == []


def test_stale_entries_are_ignored_and_reaped(registry: Path, tmp_path: Path) -> None:
    registry.mkdir(parents=True)
    dead = _dead_pid()
    stale_pid = registry / f"host-{dead}-1.json"
    stale_pid.write_text(
        json.dumps({"pid": dead, "identity": "", "sase_home": str(tmp_path)}),
        encoding="utf-8",
    )
    # A live pid whose recorded start identity no longer matches (pid reuse).
    reused = registry / f"host-{os.getpid()}-2.json"
    reused.write_text(
        json.dumps(
            {"pid": os.getpid(), "identity": "boot:1", "sase_home": str(tmp_path)}
        ),
        encoding="utf-8",
    )
    # A live pid and identity whose host released its flock while exiting.
    unlocked = registry / f"host-{os.getpid()}-3.json"
    unlocked.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "identity": process_identity_token(os.getpid()),
                "sase_home": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    garbage = registry / "host-garbage.json"
    garbage.write_text("{not json", encoding="utf-8")

    assert _live_service_hosts() == []
    assert sorted(registry.glob("host-*.json")) == []


def test_a_second_live_host_is_refused_whatever_its_home(
    foreign_host: _ServiceHostRegistryEntry, tmp_path: Path
) -> None:
    result = register_service_host(home=tmp_path / "real-home")

    assert result.refused is True
    assert result.registration is None
    assert [other.pid for other in result.others] == [foreign_host.pid]
    message = result.message or ""
    assert f"pid {foreign_host.pid}" in message
    assert foreign_host.sase_home in message
    assert f"systemctl --user stop {foreign_host.unit}" in message
    assert "sase-1t3.7.1.land" in message
    assert SERVICE_ALLOW_SECOND_HOST_ENV in message


def test_the_override_registers_a_second_host_with_a_warning(
    foreign_host: _ServiceHostRegistryEntry, tmp_path: Path
) -> None:
    result = register_service_host(
        home=tmp_path / "real-home", allow_second_reason="migration test"
    )

    assert result.refused is False
    assert result.registration is not None
    assert "migration test" in (result.message or "")
    assert {host.pid for host in _live_service_hosts()} == {
        foreign_host.pid,
        os.getpid(),
    }
    result.registration.release()


def test_run_host_refuses_while_another_home_runs_a_host(
    monkeypatch: pytest.MonkeyPatch,
    foreign_host: _ServiceHostRegistryEntry,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(SERVICE_ALLOW_SECOND_HOST_ENV, raising=False)

    def _no_children(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a refused host must not supervise children")

    with _preserved_host_globals():
        host = _ServiceHost()
        host._reconcile_once = _no_children  # type: ignore[method-assign]
        assert run_host(host, 0.05) == 1

    err = capsys.readouterr().err
    assert "refusing to start a second service host" in err
    assert f"pid {foreign_host.pid}" in err
    assert not _is_service_host_lock_held()
    assert [host.pid for host in _live_service_hosts()] == [foreign_host.pid]


def test_run_host_registers_for_its_lifetime_and_removes_on_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setenv("SASE_SERVICE_UNIT", "sase.service")
    monkeypatch.setenv("SASE_AGENT_NAME", "launcher-agent")
    monkeypatch.setattr(
        "sase.service.host_state.load_service_config", lambda: _compose({})
    )
    seen: list[_ServiceHostRegistryEntry] = []

    def _stopper() -> None:
        try:
            assert _wait_for(lambda: bool(_live_service_hosts()), timeout=10)
            seen.extend(_live_service_hosts())
        finally:
            os.kill(os.getpid(), signal.SIGTERM)

    with _preserved_host_globals():
        stopper = threading.Thread(target=_stopper, daemon=True)
        stopper.start()
        assert run_host(_ServiceHost(), 30.0) == 0
        stopper.join(timeout=15)

    assert [(h.pid, h.sase_home, h.unit, h.agent_name) for h in seen] == [
        (os.getpid(), str(home), "sase.service", "launcher-agent")
    ]
    assert _live_service_hosts() == []
    assert read_service_state().state.host is None


def _scope_lines(*units: tuple[str, str]) -> CommandResult:
    lines = [
        f"{unit} loaded {active} running SASE service host" for unit, active in units
    ]
    return CommandResult(returncode=0, stdout="\n".join(lines) + "\n")


def test_other_hosts_lists_registry_and_unregistered_scopes(
    foreign_host: _ServiceHostRegistryEntry, tmp_path: Path
) -> None:
    own = register_service_host(home=tmp_path / "real-home", allow_second_reason="t")
    calls: list[list[str]] = []

    def _runner(argv: object) -> CommandResult:
        calls.append(list(argv))  # type: ignore[call-overload]
        return _scope_lines(
            (str(foreign_host.unit), "active"),
            ("sase-service-77-9.scope", "active"),
            ("sase-service-88-9.scope", "inactive"),
        )

    try:
        others = other_service_hosts(
            current_pid=os.getpid(), home=tmp_path / "real-home", runner=_runner
        )
    finally:
        assert own.registration is not None
        own.registration.release()

    assert calls and calls[0][:3] == ["systemctl", "--user", "list-units"]
    assert [(o.source, o.pid, o.unit, o.home_differs) for o in others] == [
        ("registry", foreign_host.pid, foreign_host.unit, True),
        ("systemd", None, "sase-service-77-9.scope", None),
    ]
    assert others[0].stop_command == f"systemctl --user stop {foreign_host.unit}"
    assert others[0].agent_name == "sase-1t3.7.1.land"
    assert others[1].stop_command == "systemctl --user stop sase-service-77-9.scope"


def test_status_shows_strays_in_json_and_human_output(
    monkeypatch: pytest.MonkeyPatch,
    foreign_host: _ServiceHostRegistryEntry,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "sase.main.service_handler.service_init_plan",
        lambda **_kwargs: argparse.Namespace(blockers=(), warnings=()),
    )

    _handle_service_command(argparse.Namespace(service_subcommand="status", json=True))
    payload = json.loads(capsys.readouterr().out)
    (other,) = payload["other_hosts"]
    assert other["pid"] == foreign_host.pid
    assert other["home_differs"] is True
    assert other["stop_command"] == f"systemctl --user stop {foreign_host.unit}"

    _handle_service_command(argparse.Namespace(service_subcommand="status", json=False))
    out = capsys.readouterr().out
    assert "Other service hosts on this account (1)" in out
    assert f"systemctl --user stop {foreign_host.unit}" in out
    assert "a different SASE home" in out
