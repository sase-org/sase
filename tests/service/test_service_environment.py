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


@pytest.fixture(autouse=True)
def _ssh_agent_probe_reports_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep capture hermetic: the real ``ssh-add`` must never run here."""
    monkeypatch.setattr("sase.service.env.probe_ssh_agent", lambda _env: "ready")


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
    stale = tmp_path / "gone.sock"

    captured = capture_service_environment(
        environ={"SSH_AUTH_SOCK": str(stale), "SSH_AGENT_PID": "4242"},
        metadata_payload={},
    )

    assert "SSH_AUTH_SOCK" not in captured.values
    assert "SSH_AGENT_PID" not in captured.values
    assert len(captured.warnings) == 1
    assert str(stale) in captured.warnings[0]
    assert "platform manager" in captured.warnings[0]


def test_capture_service_environment_rejects_non_socket_ssh_agent_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    regular_file = tmp_path / "agent.sock"
    regular_file.write_text("", encoding="utf-8")

    captured = capture_service_environment(
        environ={"SSH_AUTH_SOCK": str(regular_file)},
        metadata_payload={},
    )

    assert "SSH_AUTH_SOCK" not in captured.values
    assert str(regular_file) in captured.warnings[0]


@pytest.mark.parametrize(
    ("state", "expected"),
    [("empty", "holds no identities"), ("unreachable", "cannot be reached")],
)
def test_capture_service_environment_rejects_live_agent_that_cannot_authenticate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    expected: str,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    monkeypatch.setattr("sase.service.env.probe_ssh_agent", lambda _env: state)
    with _live_socket(tmp_path / "agent.sock") as sock:
        captured = capture_service_environment(
            environ={"SSH_AUTH_SOCK": str(sock), "SSH_AGENT_PID": "4242"},
            metadata_payload={},
        )

    assert "SSH_AUTH_SOCK" not in captured.values
    assert "SSH_AGENT_PID" not in captured.values
    assert len(captured.warnings) == 1
    assert str(sock) in captured.warnings[0]
    assert expected in captured.warnings[0]
    # Capturing nothing means inheriting the platform manager's agent.
    assert "platform manager" in captured.warnings[0]


def test_capture_warning_for_empty_agent_names_the_effective_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)
    monkeypatch.setattr("sase.service.env.probe_ssh_agent", lambda _env: "empty")
    with _live_socket(tmp_path / "agent.sock") as sock:
        captured = capture_service_environment(
            environ={"SSH_AUTH_SOCK": str(sock)},
            metadata_payload={},
        )

    assert "Permission denied (publickey)" in captured.warnings[0]
    assert "may also be empty" in captured.warnings[0]


@pytest.mark.parametrize("probe_result", ["missing", "raises"])
def test_capture_service_environment_keeps_agent_when_probe_cannot_decide(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probe_result: str,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)

    def probe(_env: dict[str, str]) -> None:
        if probe_result == "raises":
            raise TimeoutError("ssh-add hung")
        return None

    monkeypatch.setattr("sase.service.env.probe_ssh_agent", probe)
    with _live_socket(tmp_path / "agent.sock") as sock:
        captured = capture_service_environment(
            environ={"SSH_AUTH_SOCK": str(sock)},
            metadata_payload={},
        )

    assert captured.values == {"SSH_AUTH_SOCK": str(sock)}
    assert captured.warnings == ()


def test_capture_service_environment_warns_when_ssh_agent_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)

    captured = capture_service_environment(
        environ={"PATH": os.defpath},
        metadata_payload={},
    )

    assert captured.values == {"PATH": os.defpath}
    assert len(captured.warnings) == 1
    assert "no SSH agent" in captured.warnings[0]
    assert "Permission denied (publickey)" in captured.warnings[0]


def test_capture_service_environment_ignores_agent_pid_without_usable_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.service.env._mobile_gateway_credential_env", lambda: None)

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
