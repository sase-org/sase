"""Tests for the service host's effective environment and git remote readiness.

``sase service init`` captures the calling shell's environment, but the host
sees that capture overlaid on the platform manager's inherited environment.
These tests pin that readiness is reported for the latter, so a healthy
interactive shell cannot mask an unhealthy service, and that readiness is the
git remote's answer rather than the contents of an agent.
"""

from __future__ import annotations

import os
import shlex
import socket
import subprocess
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

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
from sase.service.ssh_agent import (
    _probe_ssh_agent as probe_ssh_agent,
    probe_git_remote_auth,
    ssh_agent_readiness_warnings,
)

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


def test_effective_environment_keeps_manager_socket_when_persisted_is_stale(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / "env"
    write_service_environment(
        {
            "PATH": "/captured/bin",
            "SSH_AUTH_SOCK": "/tmp/ssh-gone/agent.1",
            "SSH_AGENT_PID": "9999",
        },
        path=env_path,
    )
    manager = _Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n")

    effective = effective_service_environment(
        platform_kind="linux", env_path=env_path, runner=manager
    )

    assert effective["SSH_AUTH_SOCK"] == _MANAGER_SOCK
    assert "SSH_AGENT_PID" not in effective
    assert effective["PATH"] == "/captured/bin"


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
    assert "effective environment is refused by the git remote" in warnings[0]
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


def test_effective_warning_reports_no_agent_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_remote(monkeypatch, lambda _env: "denied")

    warnings = effective_ssh_agent_warnings(
        platform_kind="linux",
        env_path=tmp_path / "absent",
        desired_env={"SSH_AUTH_SOCK": "/tmp/caller.sock"},
        runner=_Manager(show_environment="PATH=/bin\n"),
    )

    assert len(warnings) == 1
    assert "provides an SSH agent" in warnings[0]
    assert "platform manager" in warnings[0]


def test_effective_warning_is_quiet_for_a_host_that_authenticates_without_an_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``IdentityFile`` auth works against the empty manager agent; do not nag."""
    _fake_agents(monkeypatch, {_MANAGER_SOCK: "empty"})
    _fake_remote(monkeypatch, lambda _env: "ready")

    warnings = effective_ssh_agent_warnings(
        platform_kind="linux",
        env_path=tmp_path / "absent",
        desired_env={"SSH_AUTH_SOCK": "/tmp/caller.sock"},
        runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
    )

    assert warnings == []


def test_readiness_scopes_word_the_same_failure_differently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_agents(monkeypatch, {"/tmp/a.sock": "unreachable"})
    env = {"SSH_AUTH_SOCK": "/tmp/a.sock"}

    captured = ssh_agent_readiness_warnings(env)
    effective = ssh_agent_readiness_warnings(env, scope="effective")

    assert captured[0].startswith("captured service environment is refused")
    assert "effective environment is refused" in effective[0]
    assert "unreachable" in captured[0] and "unreachable" in effective[0]
    assert "docs/init.md" in captured[0] and "docs/init.md" in effective[0]


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


@pytest.mark.parametrize(
    ("stderr", "exit_code", "expected"),
    [
        (_GITHUB_AUTHENTICATED, 1, "ready"),
        (
            "Hi octo-cat! You've successfully authenticated, but GitHub does not "
            "provide shell access.",
            1,
            "ready",
        ),
        (_GITHUB_DEPLOY_KEY_AUTHENTICATED, 1, "denied"),
        (
            "Hi sase-org/sase--beads.v2! You've successfully authenticated, but "
            "GitHub does not provide shell access.",
            1,
            "denied",
        ),
        (_GITHUB_DENIED, 255, "denied"),
        ("git@github.com: Permission denied (publickey,password).", 255, "denied"),
        (
            "ssh: Could not resolve hostname github.com: Name or service not known",
            255,
            "unknown",
        ),
        (
            "ssh: connect to host github.com port 22: Connection timed out",
            255,
            "unknown",
        ),
        ("Host key verification failed.", 255, "unknown"),
        ("", 0, "unknown"),
    ],
)
def test_probe_git_remote_auth_classifies_the_remote_answer(
    tmp_path: Path, stderr: str, exit_code: int, expected: str
) -> None:
    _fake_ssh(tmp_path / "bin", stderr=stderr, exit_code=exit_code)

    assert probe_git_remote_auth({"PATH": str(tmp_path / "bin")}) == expected


def test_probe_git_remote_auth_is_unknown_when_ssh_is_missing(tmp_path: Path) -> None:
    assert probe_git_remote_auth({"PATH": str(tmp_path / "empty")}) == "unknown"


@pytest.mark.parametrize(
    "error",
    [OSError("exec format error"), subprocess.TimeoutExpired("ssh", 5)],
)
def test_probe_git_remote_auth_never_raises_and_reads_as_unknown(
    tmp_path: Path, error: Exception
) -> None:
    _fake_ssh(tmp_path / "bin", stderr=_GITHUB_AUTHENTICATED, exit_code=1)

    with patch("sase.service.ssh_agent.subprocess.run", side_effect=error):
        assert probe_git_remote_auth({"PATH": str(tmp_path / "bin")}) == "unknown"


def test_probe_git_remote_auth_asks_the_remote_unattended_with_a_network_timeout(
    tmp_path: Path,
) -> None:
    _fake_ssh(tmp_path / "bin", stderr=_GITHUB_AUTHENTICATED, exit_code=1)
    env = {
        "PATH": str(tmp_path / "bin"),
        "SSH_AUTH_SOCK": str(tmp_path / "a.sock"),
        "OPENAI_API_KEY": "s3cret",
    }

    with patch(
        "sase.service.ssh_agent.subprocess.run",
        return_value=SimpleNamespace(returncode=1, stdout="", stderr=_GITHUB_DENIED),
    ) as run:
        assert probe_git_remote_auth(env) == "denied"

    assert run.call_args.args[0] == [
        str(tmp_path / "bin" / "ssh"),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-T",
        "git@github.com",
    ]
    kwargs = run.call_args.kwargs
    assert kwargs["timeout"] == 5
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["env"] == {
        "PATH": str(tmp_path / "bin"),
        "SSH_AUTH_SOCK": str(tmp_path / "a.sock"),
    }


@pytest.mark.parametrize("scope", ["captured", "effective"])
@pytest.mark.parametrize("answer", ["ready", "unknown"])
def test_readiness_is_silent_unless_the_remote_denies(
    monkeypatch: pytest.MonkeyPatch, scope: str, answer: str
) -> None:
    _fake_remote(monkeypatch, lambda _env: answer)
    # Even an agent that holds nothing must not warn once the remote is content.
    monkeypatch.setattr("sase.service.ssh_agent._probe_ssh_agent", lambda _env: "empty")

    assert (
        ssh_agent_readiness_warnings({"SSH_AUTH_SOCK": "/tmp/a.sock"}, scope=scope)  # type: ignore[arg-type]
        == []
    )
    assert ssh_agent_readiness_warnings({}, scope=scope) == []  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("agent_state", "expected"),
    [
        ("empty", "reachable but holds no identities"),
        ("unreachable", "is unreachable"),
        ("ready", "holds identities, but the remote accepted none"),
        (None, "could not be inspected"),
    ],
)
def test_denied_readiness_words_the_warning_from_the_agent(
    monkeypatch: pytest.MonkeyPatch, agent_state: str | None, expected: str
) -> None:
    _fake_remote(monkeypatch, lambda _env: "denied")
    monkeypatch.setattr(
        "sase.service.ssh_agent._probe_ssh_agent", lambda _env: agent_state
    )

    warnings = ssh_agent_readiness_warnings({"SSH_AUTH_SOCK": "/tmp/a.sock"})

    assert len(warnings) == 1
    assert "/tmp/a.sock" in warnings[0]
    assert expected in warnings[0]
    assert "Permission denied (publickey)" in warnings[0]


def test_denied_readiness_survives_an_agent_probe_that_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_remote(monkeypatch, lambda _env: "denied")

    def boom(_env: dict[str, str]) -> str:
        raise subprocess.TimeoutExpired("ssh-add", 2)

    monkeypatch.setattr("sase.service.ssh_agent._probe_ssh_agent", boom)

    warnings = ssh_agent_readiness_warnings({"SSH_AUTH_SOCK": "/tmp/a.sock"})

    assert len(warnings) == 1
    assert "could not be inspected" in warnings[0]


@pytest.mark.parametrize("scope", ["captured", "effective"])
def test_denied_readiness_names_a_missing_agent_and_asks_for_no_recapture(
    monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    _fake_remote(monkeypatch, lambda _env: "denied")

    warnings = ssh_agent_readiness_warnings({}, scope=scope)  # type: ignore[arg-type]

    assert len(warnings) == 1
    assert "no configured IdentityFile was accepted" in warnings[0]
    assert "docs/init.md" in warnings[0]
    # Re-running init from a login shell is not a durable remedy.
    assert "re-run" not in warnings[0]


def test_plan_reports_empty_service_agent_despite_healthy_caller_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    _install_unit(resolver, {"PATH": "/bin"})
    with _live_socket(tmp_path / "caller.sock") as caller:
        _fake_agents(monkeypatch, {str(caller): "ready", _MANAGER_SOCK: "empty"})
        plan = service_init_plan(
            runner=_Manager(
                show_environment=f"PATH=/bin\nSSH_AUTH_SOCK={_MANAGER_SOCK}\n"
            ),
            environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
            executable_resolver=resolver,
        )

    # What init is about to capture is healthy; what the host would see is not.
    assert (
        _agent_warnings(
            plan.warnings, "captured service environment", "refused by the git remote"
        )
        == []
    )
    failing = _agent_warnings(
        plan.warnings, "effective environment", "refused by the git remote"
    )
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
        _fake_agents(
            monkeypatch,
            {str(caller): "ready", stale: "unreachable", _MANAGER_SOCK: "empty"},
        )
        plan = service_init_plan(
            runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
            environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
            executable_resolver=resolver,
        )

    failing = _agent_warnings(plan.warnings, "effective environment")
    assert len(failing) == 1
    assert _MANAGER_SOCK in failing[0]
    assert stale in failing[0]
    assert "no longer exists" in failing[0]


def test_plan_is_quiet_once_the_persisted_agent_matches_a_healthy_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    with _live_socket(tmp_path / "caller.sock") as caller:
        _install_unit(resolver, {"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)})
        _fake_remote(monkeypatch, lambda _env: "ready")
        plan = service_init_plan(
            runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
            environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
            executable_resolver=resolver,
        )

    assert _agent_warnings(plan.warnings, "git remote") == []
    assert _agent_warnings(plan.warnings, "only accepted credential") == []


def test_plan_skips_effective_report_when_the_unit_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    with _live_socket(tmp_path / "caller.sock") as caller:
        _fake_agents(monkeypatch, {str(caller): "ready", _MANAGER_SOCK: "empty"})
        plan = service_init_plan(
            runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
            environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
            executable_resolver=resolver,
        )

    assert (
        _agent_warnings(
            plan.warnings, "effective environment", "refused by the git remote"
        )
        == []
    )


def _durability_warnings(warnings: Sequence[str]) -> list[str]:
    return [w for w in warnings if "only accepted credential" in w]


def test_durability_warns_for_session_agent_with_denied_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    with _live_socket(tmp_path / "caller.sock") as caller:
        _fake_agents(monkeypatch, {str(caller): "ready", _MANAGER_SOCK: "empty"})
        plan = service_init_plan(
            runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
            environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
            executable_resolver=resolver,
        )

    durable = _durability_warnings(plan.warnings)
    assert len(durable) == 1
    assert str(caller) in durable[0]
    assert _MANAGER_SOCK in durable[0]
    assert "login session" in durable[0]
    assert "platform manager" in durable[0]
    assert "docs/init.md" in durable[0]
    assert durable[0].startswith("captured service environment")
    assert plan.status == "needs_attention"


def test_durability_is_silent_when_fallback_answers_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An IdentityFile host authenticates without the agent."""
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    with _live_socket(tmp_path / "caller.sock") as caller:
        _fake_remote(monkeypatch, lambda _env: "ready")
        plan = service_init_plan(
            runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
            environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
            executable_resolver=resolver,
        )

    assert _durability_warnings(plan.warnings) == []


def test_durability_is_silent_when_agent_is_managers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    with _live_socket(tmp_path / "caller.sock") as caller:
        _fake_agents(monkeypatch, {str(caller): "ready"})
        plan = service_init_plan(
            runner=_Manager(show_environment=f"SSH_AUTH_SOCK={caller}\n"),
            environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
            executable_resolver=resolver,
        )

    assert _durability_warnings(plan.warnings) == []


def test_durability_is_silent_when_primary_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    with _live_socket(tmp_path / "caller.sock") as caller:
        _fake_agents(monkeypatch, {str(caller): "unreachable", _MANAGER_SOCK: "empty"})
        plan = service_init_plan(
            runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
            environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
            executable_resolver=resolver,
        )

    assert _durability_warnings(plan.warnings) == []
    assert _agent_warnings(plan.warnings, "refused by the git remote")


@pytest.mark.parametrize(
    ("primary", "fallback"),
    [("unknown", "denied"), ("ready", "unknown"), ("unknown", "unknown")],
)
def test_durability_is_silent_when_either_answer_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary: str, fallback: str
) -> None:
    """Unknown means offline, never a durability failure."""
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    with _live_socket(tmp_path / "caller.sock") as caller:
        caller_str = str(caller)

        def answer(env: dict[str, str]) -> str:
            return primary if env.get("SSH_AUTH_SOCK") == caller_str else fallback

        _fake_remote(monkeypatch, answer)
        plan = service_init_plan(
            runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
            environ={"PATH": "/bin", "SSH_AUTH_SOCK": caller_str},
            executable_resolver=resolver,
        )

    assert _durability_warnings(plan.warnings) == []


def test_durability_effective_scope_follows_same_dedupe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    with _live_socket(tmp_path / "caller.sock") as caller:
        with _live_socket(tmp_path / "persisted.sock") as persisted:
            _install_unit(resolver, {"PATH": "/bin", "SSH_AUTH_SOCK": str(persisted)})
            _fake_agents(
                monkeypatch,
                {
                    str(caller): "ready",
                    str(persisted): "ready",
                    _MANAGER_SOCK: "empty",
                },
            )
            plan = service_init_plan(
                runner=_Manager(show_environment=f"SSH_AUTH_SOCK={_MANAGER_SOCK}\n"),
                environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
                executable_resolver=resolver,
            )

    durable = _durability_warnings(plan.warnings)
    assert len(durable) == 2
    assert any(w.startswith("captured service environment") for w in durable)
    assert any("effective environment" in w for w in durable)
    assert all(str(caller) in w or str(persisted) in w for w in durable)


def test_plan_probes_no_environment_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = _linux_plan_env(tmp_path, monkeypatch)
    _install_unit(resolver, {"PATH": "/bin"})
    with _live_socket(tmp_path / "caller.sock") as caller:
        asked: list[tuple[str | None, str | None, str | None]] = []

        def counting(env: dict[str, str]) -> str:
            asked.append(
                (
                    env.get("SSH_AUTH_SOCK"),
                    env.get("SSH_AGENT_PID"),
                    env.get("PATH"),
                )
            )
            sock = env.get("SSH_AUTH_SOCK")
            if sock == str(caller):
                return "ready"
            if sock == _MANAGER_SOCK:
                return "denied"
            return "unknown"

        monkeypatch.setattr("sase.service.ssh_agent.probe_git_remote_auth", counting)
        monkeypatch.setattr(
            "sase.service.ssh_agent._probe_ssh_agent", lambda _env: "empty"
        )
        service_init_plan(
            runner=_Manager(
                show_environment=f"PATH=/bin\nSSH_AUTH_SOCK={_MANAGER_SOCK}\n"
            ),
            environ={"PATH": "/bin", "SSH_AUTH_SOCK": str(caller)},
            executable_resolver=resolver,
        )

    assert asked
    assert len(asked) == len(set(asked))
