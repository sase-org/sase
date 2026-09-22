"""Shared fakes for effective-environment service tests."""

from __future__ import annotations

import os
import shlex
import socket
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.service.env import write_service_environment
from sase.service.platform import CommandResult, build_native_definition

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


def _fake_remote(
    monkeypatch: pytest.MonkeyPatch,
    answer: Callable[[dict[str, str]], str],
) -> None:
    """Answer the git remote probe from the environment it is asked about."""
    monkeypatch.setattr("sase.service.ssh_agent.probe_git_remote_auth", answer)


def _fake_agents(monkeypatch: pytest.MonkeyPatch, states: dict[str, str]) -> None:
    """Answer each agent by socket path: what it holds and whether the remote accepts it.

    An agent that holds identities authenticates; an empty or unreachable one is
    refused. A socket the test does not name leaves the remote unknowable.
    """

    def agent(env: dict[str, str]) -> str | None:
        return states.get(env.get("SSH_AUTH_SOCK", ""))

    def remote(env: dict[str, str]) -> str:
        return {"ready": "ready", "empty": "denied", "unreachable": "denied"}.get(
            agent(env) or "", "unknown"
        )

    monkeypatch.setattr("sase.service.ssh_agent._probe_ssh_agent", agent)
    _fake_remote(monkeypatch, remote)


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


def _fake_ssh(bin_dir: Path, *, stderr: str, exit_code: int) -> None:
    """Install an ``ssh`` that prints ``stderr`` and exits ``exit_code``."""
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "ssh"
    script.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(stderr)} >&2\nexit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


_GITHUB_AUTHENTICATED = (
    "Hi octocat! You've successfully authenticated, but GitHub does not provide "
    "shell access."
)
_GITHUB_DENIED = "git@ssh.github.com: Permission denied (publickey)."
# A deploy key logs in, but GitHub scopes it to one repo: every other push is
# refused with "Permission to <repo> denied to deploy key".
_GITHUB_DEPLOY_KEY_AUTHENTICATED = (
    "Hi bobs-org/bob! You've successfully authenticated, but GitHub does not "
    "provide shell access."
)


def _durability_warnings(warnings: Sequence[str]) -> list[str]:
    return [w for w in warnings if "only accepted credential" in w]
