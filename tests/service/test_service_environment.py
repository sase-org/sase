"""Tests for captured service-host environment files."""

from __future__ import annotations

import os
import socket
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

from sase.service.env import (
    ServiceEnvironmentError,
    capture_service_environment,
    load_service_environment,
    parse_service_environment_text,
    read_service_environment,
    render_service_environment,
    write_service_environment,
)


def _remote_answers(
    monkeypatch: pytest.MonkeyPatch, answer: str
) -> list[dict[str, str]]:
    """Make the git remote answer ``answer``; return the environments it was asked about."""
    asked: list[dict[str, str]] = []

    def probe(env: dict[str, str]) -> str:
        asked.append(dict(env))
        return answer

    monkeypatch.setattr("sase.service.ssh_agent.probe_git_remote_auth", probe)
    return asked


def test_service_environment_round_trips_non_shell_values(tmp_path) -> None:
    values = {
        "EMPTY": "",
        "MULTILINE": "one\ntwo",
        "PATH": "/bin:/opt/with space/bin",
        "QUOTE": '"hello"',
    }

    text = render_service_environment(values)

    assert parse_service_environment_text(text) == values
    path = tmp_path / "service" / "env"
    write_service_environment(values, path=path)
    assert read_service_environment(path=path) == values
    assert (path.stat().st_mode & 0o777) == 0o600


def test_service_environment_rejects_malformed_entries_without_secret_value() -> None:
    with pytest.raises(ServiceEnvironmentError) as excinfo:
        parse_service_environment_text("API_KEY=not-json-secret\n")

    message = str(excinfo.value)
    assert "API_KEY" in message
    assert "not-json-secret" not in message


def test_capture_service_environment_uses_provider_and_gateway_declared_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.service.env._mobile_gateway_credential_env",
        lambda: "FCM_TOKEN",
    )
    payload = {
        "providers": {
            "codex": {
                "auth_evidence": {
                    "api_key_env_vars": ["OPENAI_API_KEY"],
                },
            }
        }
    }

    captured = capture_service_environment(
        environ={
            "PATH": os.defpath,
            "SASE_CODEX_PATH": "/tools/codex",
            "OPENAI_API_KEY": "secret",
            "FCM_TOKEN": "secret2",
            "HOME": "/not/captured",
        },
        metadata_payload=payload,
    )

    assert captured.values == {
        "FCM_TOKEN": "secret2",
        "OPENAI_API_KEY": "secret",
        "PATH": os.defpath,
        "SASE_CODEX_PATH": "/tools/codex",
    }
    assert captured.redacted_values["OPENAI_API_KEY"] == "[captured]"


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


def test_capture_service_environment_captures_live_ssh_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    with _live_socket(tmp_path / "agent.sock") as sock:
        captured = capture_service_environment(
            environ={
                "PATH": os.defpath,
                "SSH_AUTH_SOCK": str(sock),
                "SSH_AGENT_PID": "4242",
            },
            metadata_payload={},
        )

    assert captured.values == {
        "PATH": os.defpath,
        "SSH_AGENT_PID": "4242",
        "SSH_AUTH_SOCK": str(sock),
    }
    assert captured.warnings == ()
    assert captured.redacted_values["SSH_AUTH_SOCK"] == "[captured]"


def test_capture_service_environment_captures_agent_without_pid_silently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    with _live_socket(tmp_path / "agent.sock") as sock:
        captured = capture_service_environment(
            environ={"SSH_AUTH_SOCK": str(sock)},
            metadata_payload={},
        )

    assert captured.values == {"SSH_AUTH_SOCK": str(sock)}
    assert captured.warnings == ()


def test_capture_service_environment_rejects_stale_ssh_agent_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    _remote_answers(monkeypatch, "denied")
    stale = tmp_path / "gone.sock"

    captured = capture_service_environment(
        environ={"SSH_AUTH_SOCK": str(stale), "SSH_AGENT_PID": "4242"},
        metadata_payload={},
    )

    assert "SSH_AUTH_SOCK" not in captured.values
    assert "SSH_AGENT_PID" not in captured.values
    assert len(captured.warnings) == 2
    assert str(stale) in captured.warnings[0]
    assert "platform manager" in captured.warnings[0]
    assert "refused by the git remote" in captured.warnings[1]


def test_capture_service_environment_rejects_non_socket_ssh_agent_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    _remote_answers(monkeypatch, "denied")
    regular_file = tmp_path / "agent.sock"
    regular_file.write_text("", encoding="utf-8")

    captured = capture_service_environment(
        environ={"SSH_AUTH_SOCK": str(regular_file)},
        metadata_payload={},
    )

    assert "SSH_AUTH_SOCK" not in captured.values
    assert str(regular_file) in captured.warnings[0]


@pytest.mark.parametrize("answer", ["ready", "unknown"])
def test_capture_service_environment_stays_quiet_about_a_stale_socket_that_is_harmless(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    """A stale socket left in a tmux session must not warn a host that authenticates."""
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    _remote_answers(monkeypatch, answer)

    captured = capture_service_environment(
        environ={"SSH_AUTH_SOCK": str(tmp_path / "gone.sock")},
        metadata_payload={},
    )

    assert captured.values == {}
    assert captured.warnings == ()


@pytest.mark.parametrize("agent_state", ["empty", "unreachable"])
def test_capture_service_environment_captures_a_live_agent_that_holds_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_state: str,
) -> None:
    """Agent contents do not decide readiness; ``IdentityFile`` can still work."""
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    monkeypatch.setattr(
        "sase.service.ssh_agent._probe_ssh_agent", lambda _env: agent_state
    )
    _remote_answers(monkeypatch, "ready")
    with _live_socket(tmp_path / "agent.sock") as sock:
        captured = capture_service_environment(
            environ={"SSH_AUTH_SOCK": str(sock), "SSH_AGENT_PID": "4242"},
            metadata_payload={},
        )

    assert captured.values == {"SSH_AUTH_SOCK": str(sock), "SSH_AGENT_PID": "4242"}
    assert captured.warnings == ()


@pytest.mark.parametrize(
    ("agent_state", "expected"),
    [("empty", "holds no identities"), ("unreachable", "is unreachable")],
)
def test_capture_warning_for_a_refused_agent_still_captures_it_and_names_the_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_state: str,
    expected: str,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    monkeypatch.setattr(
        "sase.service.ssh_agent._probe_ssh_agent", lambda _env: agent_state
    )
    _remote_answers(monkeypatch, "denied")
    with _live_socket(tmp_path / "agent.sock") as sock:
        captured = capture_service_environment(
            environ={"SSH_AUTH_SOCK": str(sock)},
            metadata_payload={},
        )

    assert captured.values == {"SSH_AUTH_SOCK": str(sock)}
    assert len(captured.warnings) == 1
    assert str(sock) in captured.warnings[0]
    assert expected in captured.warnings[0]
    assert "Permission denied (publickey)" in captured.warnings[0]


def test_capture_service_environment_asks_the_remote_about_what_it_captures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    asked = _remote_answers(monkeypatch, "ready")
    with _live_socket(tmp_path / "agent.sock") as sock:
        capture_service_environment(
            environ={
                "PATH": "/captured/bin",
                "SSH_AUTH_SOCK": str(sock),
                "OPENAI_API_KEY": "s3cret",
            },
            metadata_payload={},
        )

    assert asked == [{"PATH": "/captured/bin", "SSH_AUTH_SOCK": str(sock)}]


@pytest.mark.parametrize("answer", ["ready", "unknown"])
def test_capture_service_environment_with_no_agent_at_all_captures_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    """A host that authenticates by ``IdentityFile`` needs no agent and no warning."""
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    _remote_answers(monkeypatch, answer)

    captured = capture_service_environment(
        environ={"PATH": os.defpath},
        metadata_payload={},
    )

    assert captured.values == {"PATH": os.defpath}
    assert captured.warnings == ()


def test_capture_service_environment_warns_when_no_agent_and_remote_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    _remote_answers(monkeypatch, "denied")

    captured = capture_service_environment(
        environ={"PATH": os.defpath},
        metadata_payload={},
    )

    assert captured.values == {"PATH": os.defpath}
    assert len(captured.warnings) == 1
    assert "no SSH agent" in captured.warnings[0]
    assert "Permission denied (publickey)" in captured.warnings[0]
    assert "docs/init.md" in captured.warnings[0]


def test_capture_service_environment_ignores_agent_pid_without_usable_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    _remote_answers(monkeypatch, "denied")

    captured = capture_service_environment(
        environ={"SSH_AGENT_PID": "4242"},
        metadata_payload={},
    )

    assert captured.values == {}
    assert len(captured.warnings) == 1


def test_load_service_environment_override_existing_only_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "env"
    write_service_environment({"PATH": "/captured/bin"}, path=path)
    monkeypatch.setenv("SASE_SERVICE_ENV", str(path))
    monkeypatch.setenv("PATH", "/interactive/bin")

    applied = load_service_environment(override_existing=False)
    assert os.environ["PATH"] == "/interactive/bin"
    assert "PATH" not in applied

    applied = load_service_environment(override_existing=True)
    assert os.environ["PATH"] == "/captured/bin"
    assert "PATH" in applied


def test_load_service_environment_ignores_stale_agent_in_both_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "env"
    stale = tmp_path / "gone.sock"
    write_service_environment(
        {
            "PATH": "/captured/bin",
            "EXTRA": "1",
            "SSH_AUTH_SOCK": str(stale),
            "SSH_AGENT_PID": "9999",
        },
        path=path,
    )
    monkeypatch.setenv("SASE_SERVICE_ENV", str(path))
    monkeypatch.setenv("SSH_AUTH_SOCK", "/manager/agent.sock")
    monkeypatch.setenv("SSH_AGENT_PID", "1111")
    monkeypatch.setenv("PATH", "/manager/bin")

    applied = load_service_environment(override_existing=True)
    assert os.environ["SSH_AUTH_SOCK"] == "/manager/agent.sock"
    assert os.environ["SSH_AGENT_PID"] == "1111"
    assert "SSH_AUTH_SOCK" not in applied
    assert "SSH_AGENT_PID" not in applied
    assert os.environ["PATH"] == "/captured/bin"
    assert "PATH" in applied
    assert os.environ["EXTRA"] == "1"
    assert "EXTRA" in applied

    monkeypatch.setenv("SSH_AUTH_SOCK", "/manager/agent.sock")
    applied = load_service_environment(override_existing=False)
    assert os.environ["SSH_AUTH_SOCK"] == "/manager/agent.sock"
    assert "SSH_AUTH_SOCK" not in applied
    assert "SSH_AGENT_PID" not in applied


def test_load_service_environment_applies_live_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _live_socket(tmp_path / "agent.sock") as sock:
        path = tmp_path / "env"
        write_service_environment(
            {
                "PATH": "/captured/bin",
                "SSH_AUTH_SOCK": str(sock),
                "SSH_AGENT_PID": "4242",
            },
            path=path,
        )
        monkeypatch.setenv("SASE_SERVICE_ENV", str(path))
        monkeypatch.setenv("SSH_AUTH_SOCK", "/old.sock")
        monkeypatch.setenv("SSH_AGENT_PID", "1111")
        monkeypatch.setenv("PATH", "/old/bin")

        applied = load_service_environment(override_existing=True)
        assert os.environ["SSH_AUTH_SOCK"] == str(sock)
        assert os.environ["SSH_AGENT_PID"] == "4242"
        assert "SSH_AUTH_SOCK" in applied
        assert "SSH_AGENT_PID" in applied
        assert os.environ["PATH"] == "/captured/bin"
