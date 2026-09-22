"""Effective service environment overlay and effective-agent warnings."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from sase.service.effective_env import (
    _effective_service_environment as effective_service_environment,
    effective_ssh_agent_warnings,
)
from sase.service.env import write_service_environment
from sase.service.platform import CommandResult
from sase.service.ssh_agent import ssh_agent_readiness_warnings
from tests.service.service_effective_env_helpers import (
    _MANAGER_SOCK,
    _Manager,
    _fake_agents,
    _fake_remote,
)


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
