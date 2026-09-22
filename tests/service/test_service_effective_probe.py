"""SSH-agent and git-remote probes plus generic readiness wording."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.service.ssh_agent import (
    _probe_ssh_agent as probe_ssh_agent,
    probe_git_remote_auth,
    ssh_agent_readiness_warnings,
)
from tests.service.service_effective_env_helpers import (
    _GITHUB_AUTHENTICATED,
    _GITHUB_DENIED,
    _GITHUB_DEPLOY_KEY_AUTHENTICATED,
    _fake_remote,
    _fake_ssh,
    _fake_ssh_add,
)


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
