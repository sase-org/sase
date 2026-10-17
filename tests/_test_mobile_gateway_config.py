"""Mobile gateway config and launch tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import sase.integrations.mobile_gateway as mobile_gateway
from sase.integrations.mobile_gateway import (
    _MobileGatewayConfig,
    _MobileGatewayError,
    _load_mobile_gateway_config,
    _prepare_mobile_gateway_launch,
)
from tests._mobile_gateway_test_helpers import make_args


def test_load_mobile_gateway_config_defaults() -> None:
    with patch("sase.integrations.mobile_gateway.load_merged_config", return_value={}):
        assert _load_mobile_gateway_config() == _MobileGatewayConfig()


def test_resolve_gateway_command_checks_active_python_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gateway = tmp_path / "sase_gateway"
    gateway.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(mobile_gateway.shutil, "which", lambda _name: None)
    monkeypatch.setattr(mobile_gateway.sys, "executable", str(tmp_path / "python"))

    assert mobile_gateway.resolve_gateway_command() == (str(gateway),)


def test_load_mobile_gateway_config_normalizes_values(tmp_path: Path) -> None:
    with patch(
        "sase.integrations.mobile_gateway.load_merged_config",
        return_value={
            "mobile_gateway": {
                "bind_address": " 127.0.0.1 ",
                "port": "7630",
                "state_dir": str(tmp_path / "state"),
                "allow_non_loopback": True,
                "command": "sase_gateway --extra",
                "agent_bridge_command": "sase",
                "helper_bridge_command": "sase-helper",
                "push_provider": "fcm",
                "fcm_project_id": "demo-project",
                "fcm_service_account_json": str(tmp_path / "fcm.json"),
                "fcm_credential_env": "SASE_FCM_CREDENTIAL",
                "fcm_dry_run": True,
                "push_timeout_seconds": "2.0",
                "push_retry_limit": "3",
                "startup_timeout_seconds": "2.5",
            }
        },
    ):
        assert _load_mobile_gateway_config() == _MobileGatewayConfig(
            bind_address="127.0.0.1",
            port=7630,
            state_dir=tmp_path / "state",
            allow_non_loopback=True,
            command=("sase_gateway", "--extra"),
            agent_bridge_command=("sase",),
            helper_bridge_command=("sase-helper",),
            push_provider="fcm",
            fcm_project_id="demo-project",
            fcm_service_account_json=tmp_path / "fcm.json",
            fcm_credential_env="SASE_FCM_CREDENTIAL",
            fcm_dry_run=True,
            push_timeout_seconds=2.0,
            push_retry_limit=3,
            startup_timeout_seconds=2.5,
        )


def test_prepare_launch_builds_default_loopback_argv() -> None:
    launch = _prepare_mobile_gateway_launch(
        make_args(),
        config=_MobileGatewayConfig(command=("sase_gateway",)),
    )

    assert launch.argv == ["sase_gateway", "--bind", "127.0.0.1:7629"]
    assert launch.url == "http://127.0.0.1:7629"


def test_prepare_launch_rejects_non_loopback_without_opt_in() -> None:
    with pytest.raises(_MobileGatewayError, match="refusing to bind"):
        _prepare_mobile_gateway_launch(
            make_args(bind_address="0.0.0.0"),
            config=_MobileGatewayConfig(command=("sase_gateway",)),
        )


def test_prepare_launch_propagates_non_loopback_opt_in() -> None:
    launch = _prepare_mobile_gateway_launch(
        make_args(bind_address="0.0.0.0", allow_non_loopback=True),
        config=_MobileGatewayConfig(command=("sase_gateway",)),
    )

    assert launch.argv == [
        "sase_gateway",
        "--bind",
        "0.0.0.0:7629",
        "--allow-non-loopback",
    ]
    assert launch.url == "http://127.0.0.1:7629"


def test_prepare_launch_missing_binary_error_text() -> None:
    with (
        patch(
            "sase.integrations.mobile_gateway._resolve_gateway_command", return_value=()
        ),
        pytest.raises(_MobileGatewayError, match="mobile gateway binary not found"),
    ):
        _prepare_mobile_gateway_launch(make_args(), config=_MobileGatewayConfig())


def test_prepare_launch_includes_state_dir_and_cli_overrides(tmp_path: Path) -> None:
    launch = _prepare_mobile_gateway_launch(
        make_args(
            port=9999, state_dir=str(tmp_path), gateway_command="/bin/sase_gateway"
        ),
        config=_MobileGatewayConfig(command=("ignored",)),
    )

    assert launch.argv == [
        "/bin/sase_gateway",
        "--bind",
        "127.0.0.1:9999",
        "--sase-home",
        str(tmp_path),
    ]


def test_prepare_launch_includes_non_secret_push_settings(tmp_path: Path) -> None:
    launch = _prepare_mobile_gateway_launch(
        make_args(
            gateway_command="/bin/sase_gateway",
            push_provider="fcm",
            fcm_project_id="demo-project",
            fcm_service_account_json=str(tmp_path / "fcm.json"),
            fcm_credential_env="SASE_FCM_TOKEN",
            fcm_dry_run=True,
            push_timeout_seconds=2.5,
            push_retry_limit=3,
        ),
        config=_MobileGatewayConfig(command=("ignored",)),
    )

    assert launch.argv == [
        "/bin/sase_gateway",
        "--bind",
        "127.0.0.1:7629",
        "--push-provider",
        "fcm",
        "--fcm-project-id",
        "demo-project",
        "--fcm-service-account-json",
        str(tmp_path / "fcm.json"),
        "--fcm-credential-env",
        "SASE_FCM_TOKEN",
        "--fcm-dry-run",
        "--push-timeout-seconds",
        "2.5",
        "--push-retry-limit",
        "3",
    ]
    assert "secret" not in " ".join(launch.argv).lower()


def test_prepare_service_launch_uses_direct_gateway_argv() -> None:
    with (
        patch(
            "sase.integrations.mobile_gateway.load_merged_config",
            return_value={"mobile_gateway": {"command": "sase_gateway"}},
        ),
        patch(
            "sase.integrations.mobile_gateway._sase_command",
            return_value=("sase",),
        ),
    ):
        launch = mobile_gateway.prepare_mobile_gateway_service_launch()

    # The gateway appends `mobile agent-bridge/<helper-bridge> <op>` itself,
    # so the service launch must pass the bare sase executable (regression:
    # the full subcommand path made every bridge call fail arg parsing).
    assert launch.argv == [
        "sase_gateway",
        "--bind",
        "127.0.0.1:7629",
        "--agent-bridge-command",
        "sase",
        "--helper-bridge-command",
        "sase",
    ]
    assert "gateway start" not in " ".join(launch.argv)
