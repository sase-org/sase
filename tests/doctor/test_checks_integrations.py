"""Tests for doctor integration checks."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_integrations import _check_mobile_push_config
from sase.integrations.mobile_gateway import MobileGatewayConfig


def test_mobile_push_config_skips_when_disabled() -> None:
    check = _check_mobile_push_config(config=MobileGatewayConfig())

    assert check.id == "integrations.mobile_push_config"
    assert check.group == "integrations"
    assert check.status == "SKIP"
    assert check.summary == "mobile push is disabled"
    assert check.data["push_enabled"] is False


def test_mobile_push_config_ok_for_test_provider() -> None:
    check = _check_mobile_push_config(config=MobileGatewayConfig(push_provider="test"))

    assert check.status == "OK"
    assert check.summary == "mobile push uses the test provider"
    assert check.data["push_provider"] == "test"


def test_mobile_push_config_ok_for_fcm_dry_run_without_credentials() -> None:
    check = _check_mobile_push_config(
        config=MobileGatewayConfig(push_provider="fcm", fcm_dry_run=True)
    )

    assert check.status == "OK"
    assert check.summary == "FCM push is configured for dry-run mode"
    assert check.data["fcm_dry_run"] is True
    assert check.data["fcm_project_id_configured"] is False
    assert check.data["fcm_auth_source_configured"] is False


def test_mobile_push_config_ok_for_complete_fcm_service_account_config() -> None:
    check = _check_mobile_push_config(
        config=MobileGatewayConfig(
            push_provider="fcm",
            fcm_project_id="demo-project",
            fcm_service_account_json=Path("/secrets/fcm.json"),
        )
    )

    assert check.status == "OK"
    assert "project ID and credential source" in check.summary
    assert check.data["fcm_project_id_configured"] is True
    assert check.data["fcm_service_account_json_configured"] is True
    assert check.data["fcm_env_var_configured"] is False
    assert check.data["fcm_auth_source_configured"] is True


def test_mobile_push_config_ok_for_complete_fcm_env_config() -> None:
    check = _check_mobile_push_config(
        config=MobileGatewayConfig(
            push_provider="fcm",
            fcm_project_id="demo-project",
            fcm_credential_env="SASE_FCM_SERVICE_ACCOUNT_JSON",
        )
    )

    assert check.status == "OK"
    assert check.data["fcm_service_account_json_configured"] is False
    assert check.data["fcm_env_var_configured"] is True
    assert check.data["fcm_auth_source_configured"] is True


def test_mobile_push_config_errors_when_fcm_project_id_is_missing() -> None:
    check = _check_mobile_push_config(
        config=MobileGatewayConfig(
            push_provider="fcm",
            fcm_credential_env="SASE_FCM_SERVICE_ACCOUNT_JSON",
        )
    )

    assert check.status == "ERROR"
    assert check.summary == "FCM push is enabled but required config is missing"
    assert check.details == ("missing: mobile_gateway.fcm_project_id",)
    assert any("fcm_project_id" in step for step in check.next_steps)


def test_mobile_push_config_errors_when_fcm_credential_source_is_missing() -> None:
    check = _check_mobile_push_config(
        config=MobileGatewayConfig(
            push_provider="fcm",
            fcm_project_id="demo-project",
        )
    )

    assert check.status == "ERROR"
    assert check.details == (
        "missing: mobile_gateway.fcm_service_account_json or mobile_gateway.fcm_credential_env",
    )
    assert check.data["fcm_auth_source_configured"] is False


def test_mobile_push_config_errors_with_both_required_fcm_fields_missing() -> None:
    check = _check_mobile_push_config(config=MobileGatewayConfig(push_provider="fcm"))

    assert check.status == "ERROR"
    assert check.details == (
        "missing: mobile_gateway.fcm_project_id",
        "missing: mobile_gateway.fcm_service_account_json or mobile_gateway.fcm_credential_env",
    )
