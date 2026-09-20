"""Tests for the service host's effective environment and SSH agent readiness.

``sase service init`` captures the calling shell's environment, but the host
sees that capture overlaid on the platform manager's inherited environment.
These tests pin that readiness is reported for the latter, so a healthy
interactive shell cannot mask an unhealthy service.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.feature_flags import override_flags
from sase.service.effective_env import (
    _effective_service_environment as effective_service_environment,
    effective_ssh_agent_warnings,
)
from sase.service.env import write_service_environment
from sase.service.platform import (
    CommandResult,
    build_native_definition,
    service_init_plan,
)
from sase.service.ssh_agent import probe_ssh_agent, ssh_agent_readiness_warnings

_MANAGER_SOCK = "/run/user/1000/openssh_agent"


class _Manager:
    """Injected platform manager answering the commands the plan issues."""

    def __init__(
        self,
        *,
        show_environment: str = "",
        show_environment_rc: int = 0,
        launchctl_getenv: str = "",
    ) -> None:
        self._show_environment = show_environment
        self._show_environment_rc = show_environment_rc
        self._launchctl_getenv = launchctl_getenv

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(argv)
        if command == ("systemctl", "--user", "show-environment"):
            return CommandResult(self._show_environment_rc, self._show_environment)
        if command[:2] == ("launchctl", "getenv"):
            return CommandResult(0, self._launchctl_getenv)
        if command[:3] == ("systemctl", "--user", "is-enabled"):
            return CommandResult(1, "disabled\n")
        if command[:3] == ("systemctl", "--user", "is-active"):
            return CommandResult(3, "inactive\n")
        if command[0] == "loginctl":
            return CommandResult(0, "yes\n")
        return CommandResult(0, "")


@contextmanager
def _live_socket(path: Path) -> Generator[Path, None, None]:
    # AF_UNIX addresses cap at ~108 bytes and pytest tmp paths can exceed that,
    # so bind by a relative name from the socket's directory.
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    cwd = os.getcwd()
    try:
        os.chdir(path.parent)
        try:
            server.bind(path.name)
        finally:
            os.chdir(cwd)
        yield path
    finally:
        server.close()


def _fake_agents(monkeypatch: pytest.MonkeyPatch, states: dict[str, str]) -> None:
    """Answer each agent's probe by socket path, for capture and readiness alike."""

    def probe(env: dict[str, str]) -> str | None:
        return states.get(env.get("SSH_AUTH_SOCK", ""))

    monkeypatch.setattr("sase.service.ssh_agent.probe_ssh_agent", probe)
    monkeypatch.setattr("sase.service.env.probe_ssh_agent", probe)


def _linux_plan_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[], str]:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "sase.service.platform.collect_agent_cli_statuses", lambda **_k: ()
    )
    monkeypatch.setattr(
        "sase.integrations.mobile_gateway.load_mobile_gateway_config",
        lambda: SimpleNamespace(command=()),
    )
    exe = tmp_path / "bin" / "sase"
    exe.parent.mkdir(exist_ok=True)
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    return lambda: str(exe)


def _install_unit(resolver: Callable[[], str], persisted: dict[str, str]) -> None:
    definition, _blockers, _executable = build_native_definition(
        force=False, executable_resolver=resolver
    )
    definition.definition_path.parent.mkdir(parents=True, exist_ok=True)
    definition.definition_path.write_text(definition.content, encoding="utf-8")
    write_service_environment(persisted, path=definition.env_path)


def _agent_warnings(warnings: Sequence[str], *needles: str) -> list[str]:
    return [w for w in warnings if all(needle in w for needle in needles)]


def _fake_ssh_add(bin_dir: Path, exit_code: int) -> None:
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "ssh-add"
    script.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    script.chmod(0o755)


@pytest.mark.parametrize(
    ("exit_code", "expected"),
    [(0, "ready"), (1, "empty"), (2, "unreachable"), (7, "ready")],
)
def test_probe_ssh_agent_maps_ssh_add_exit_codes(
    tmp_path: Path, exit_code: int, expected: str
) -> None:
    _fake_ssh_add(tmp_path / "bin", exit_code)

    state = probe_ssh_agent(
        {"PATH": str(tmp_path / "bin"), "SSH_AUTH_SOCK": str(tmp_path / "a.sock")}
    )

    assert state == expected


def test_probe_ssh_agent_returns_none_when_ssh_add_is_missing(tmp_path: Path) -> None:
    assert probe_ssh_agent({"PATH": str(tmp_path / "empty")}) is None


def test_effective_environment_overlays_persisted_file_on_manager_environment(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / "env"
    write_service_environment({"PATH": "/captured/bin", "EXTRA": "1"}, path=env_path)
    manager = _Manager(
        show_environment=f"PATH=/manager/bin\nSSH_AUTH_SOCK={_MANAGER_SOCK}\nLANG=C\n"
    )

    effective = effective_service_environment(
        platform_kind="linux", env_path=env_path, runner=manager
    )

    assert effective == {
        "PATH": "/captured/bin",
        "SSH_AUTH_SOCK": _MANAGER_SOCK,
        "LANG": "C",
        "EXTRA": "1",
    }


def test_effective_environment_reads_darwin_agent_from_launchctl(
    tmp_path: Path,
) -> None:
    effective = effective_service_environment(
        platform_kind="darwin",
        env_path=tmp_path / "absent",
        runner=_Manager(launchctl_getenv="/private/tmp/launchd/Listeners\n"),
    )

    assert effective == {"SSH_AUTH_SOCK": "/private/tmp/launchd/Listeners"}


def test_effective_environment_survives_manager_failure_and_bad_file(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / "env"
    env_path.write_text("not a valid entry\n", encoding="utf-8")

    def broken_runner(_argv: Sequence[str]) -> CommandResult:
        raise OSError("no systemctl")

    assert (
        effective_service_environment(
            platform_kind="linux", env_path=env_path, runner=broken_runner
        )
        == {}
    )
    assert effective_service_environment(
        platform_kind="linux",
        env_path=env_path,
        runner=_Manager(show_environment="SSH_AUTH_SOCK=/x\n"),
    ) == {"SSH_AUTH_SOCK": "/x"}
    assert (
        effective_service_environment(
            platform_kind="linux",
            env_path=tmp_path / "absent",
            runner=_Manager(
                show_environment="SSH_AUTH_SOCK=/x\n", show_environment_rc=1
            ),
        )
        == {}
    )


def test_effective_warning_names_the_agent_the_service_would_really_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_agents(monkeypatch, {_MANAGER_SOCK: "empty"})

    warnings = effective_ssh_agent_warnings(
        platform_kind="linux",
        env_path=tmp_path / "absent",
        desired_env={"SSH_AUTH_SOCK": "/tmp/caller.sock"},
        runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
    )

    assert len(warnings) == 1
    assert "effective SSH agent" in warnings[0]
    assert _MANAGER_SOCK in warnings[0]
    assert "holds no identities" in warnings[0]
    assert "docs/init.md" in warnings[0]


def test_effective_warning_is_quiet_when_it_matches_the_captured_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_agents(monkeypatch, {_MANAGER_SOCK: "empty"})

    warnings = effective_ssh_agent_warnings(
        platform_kind="linux",
        env_path=tmp_path / "absent",
        desired_env={"SSH_AUTH_SOCK": _MANAGER_SOCK},
        runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
    )

    assert warnings == []


def test_effective_warning_reports_no_agent_anywhere(tmp_path: Path) -> None:
    warnings = effective_ssh_agent_warnings(
        platform_kind="linux",
        env_path=tmp_path / "absent",
        desired_env={"SSH_AUTH_SOCK": "/tmp/caller.sock"},
        runner=_Manager(show_environment="PATH=/bin\n"),
    )

    assert len(warnings) == 1
    assert "carries no SSH agent" in warnings[0]
    assert "platform manager" in warnings[0]


def test_readiness_scopes_word_the_same_failure_differently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_agents(monkeypatch, {"/tmp/a.sock": "unreachable"})
    env = {"SSH_AUTH_SOCK": "/tmp/a.sock"}

    captured = ssh_agent_readiness_warnings(env)
    effective = ssh_agent_readiness_warnings(env, scope="effective")

    assert "re-run `sase service init`" in captured[0]
    assert "effective SSH agent" in effective[0]
    assert "unreachable" in captured[0] and "unreachable" in effective[0]


def test_plan_reports_empty_service_agent_despite_healthy_caller_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    _install_unit(resolver, {"PATH": "/bin"})
    with _live_socket(tmp_path / "caller.sock") as caller:
        _fake_agents(monkeypatch, {str(caller): "ready", _MANAGER_SOCK: "empty"})
        with override_flags(service_host=True):
            plan = service_init_plan(
                runner=_Manager(
                    show_environment=f"PATH=/bin\nSSH_AUTH_SOCK={_MANAGER_SOCK}\n"
                ),
                environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
                executable_resolver=resolver,
            )

    # What init is about to capture is healthy; what the host would see is not.
    assert _agent_warnings(plan.warnings, "captured service environment") == []
    failing = _agent_warnings(plan.warnings, "effective SSH agent")
    assert len(failing) == 1
    assert _MANAGER_SOCK in failing[0]
    assert plan.status == "needs_attention"


def test_plan_reports_stale_persisted_agent_despite_healthy_caller_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    stale = "/tmp/ssh-gone/agent.1"
    _install_unit(resolver, {"PATH": "/bin", "SSH_AUTH_SOCK": stale})
    with _live_socket(tmp_path / "caller.sock") as caller:
        _fake_agents(monkeypatch, {str(caller): "ready", stale: "unreachable"})
        with override_flags(service_host=True):
            plan = service_init_plan(
                runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
                environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
                executable_resolver=resolver,
            )

    failing = _agent_warnings(plan.warnings, "effective SSH agent", "unreachable")
    assert len(failing) == 1
    assert stale in failing[0]


def test_plan_is_quiet_once_the_persisted_agent_matches_a_healthy_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    with _live_socket(tmp_path / "caller.sock") as caller:
        _install_unit(resolver, {"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)})
        _fake_agents(monkeypatch, {str(caller): "ready", _MANAGER_SOCK: "empty"})
        with override_flags(service_host=True):
            plan = service_init_plan(
                runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
                environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
                executable_resolver=resolver,
            )

    assert _agent_warnings(plan.warnings, "SSH agent") == []


def test_plan_skips_effective_report_when_the_unit_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    with _live_socket(tmp_path / "caller.sock") as caller:
        _fake_agents(monkeypatch, {str(caller): "ready", _MANAGER_SOCK: "empty"})
        with override_flags(service_host=True):
            plan = service_init_plan(
                runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
                environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
                executable_resolver=resolver,
            )

    assert _agent_warnings(plan.warnings, "effective SSH agent") == []
