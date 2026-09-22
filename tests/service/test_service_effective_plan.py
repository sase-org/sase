"""service_init_plan reporting for effective and session agents."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from sase.service.platform import service_init_plan
from tests.service.service_effective_env_helpers import (
    _MANAGER_SOCK,
    _Manager,
    _agent_warnings,
    _durability_warnings,
    _fake_agents,
    _fake_remote,
    _install_unit,
    _linux_plan_env,
    _live_socket,
)


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
