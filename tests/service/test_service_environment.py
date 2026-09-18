"""Tests for captured service-host environment files."""

from __future__ import annotations

import os

import pytest

from sase.service.env import (
    ServiceEnvironmentError,
    capture_service_environment,
    parse_service_environment_text,
    read_service_environment,
    render_service_environment,
    write_service_environment,
)


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
