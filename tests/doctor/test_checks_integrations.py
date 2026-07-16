"""Tests for doctor integration checks."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_integrations import (
    _check_mobile_gateway_binary,
    _check_mobile_push_config,
    _check_telegram_commands,
    integration_check_specs,
)
from sase.doctor.runner import DoctorContext
from sase.integrations.mobile_gateway import MobileGatewayConfig


def test_integration_check_specs_registers_mobile_gateway_binary_as_deep(
    tmp_path: Path,
) -> None:
    specs = integration_check_specs(
        DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    )

    assert [spec.id for spec in specs] == [
        "integrations.mobile_push_config",
        "integrations.telegram_commands",
        "integrations.mobile_gateway_binary",
    ]
    assert specs[1].deep is False
    assert specs[2].deep is True


def test_telegram_commands_skips_when_none_are_configured() -> None:
    check = _check_telegram_commands(config={"telegram": {"commands": {}}})

    assert check.id == "integrations.telegram_commands"
    assert check.group == "integrations"
    assert check.status == "SKIP"
    assert check.summary == "no custom Telegram commands are configured"
    assert check.data["configured_commands"] == 0


def test_telegram_commands_reports_resolvable_run_values() -> None:
    check = _check_telegram_commands(
        config={
            "telegram": {
                "commands": {
                    "tasks": {
                        "description": "Tasks dashboard",
                        "run": "tg_cmd_tasks --note dash.md",
                    }
                }
            }
        },
        command_head_available=lambda head: head == "tg_cmd_tasks",
    )

    assert check.status == "OK"
    assert check.summary == "all 1 custom Telegram command executables resolve"
    assert check.details == ("tasks: tg_cmd_tasks (resolved)",)
    assert check.data["resolved_commands"] == 1
    assert check.data["command_results"][0]["command_head"] == "tg_cmd_tasks"


def test_telegram_commands_warns_for_unresolvable_run_values() -> None:
    check = _check_telegram_commands(
        config={
            "telegram": {
                "commands": {
                    "report": {
                        "description": "Other report",
                        "run": "missing_report --verbose",
                    },
                    "tasks": {
                        "description": "Tasks dashboard",
                        "run": "tg_cmd_tasks",
                    },
                }
            }
        },
        command_head_available=lambda head: head == "tg_cmd_tasks",
    )

    assert check.status == "WARN"
    assert check.summary == (
        "1 of 2 custom Telegram command executables do not resolve"
    )
    assert check.details == (
        "report: missing_report (not found)",
        "tasks: tg_cmd_tasks (resolved)",
    )
    assert check.data["configured_commands"] == 2
    assert check.data["resolved_commands"] == 1
    assert check.data["unresolved_commands"] == 1
    assert any("telegram.commands" in step for step in check.next_steps)


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


def test_mobile_gateway_binary_skips_when_mobile_is_unused() -> None:
    def fail_resolver() -> tuple[str, ...]:
        raise AssertionError("unused mobile config should not resolve gateway binary")

    check = _check_mobile_gateway_binary(
        config=MobileGatewayConfig(),
        resolve_gateway_command=fail_resolver,
    )

    assert check.id == "integrations.mobile_gateway_binary"
    assert check.group == "integrations"
    assert check.status == "SKIP"
    assert check.summary == "mobile gateway is not configured"
    assert check.data["mobile_configured"] is False
    assert check.data["command_resolved"] is False


def test_mobile_gateway_binary_warns_when_configured_binary_is_missing() -> None:
    check = _check_mobile_gateway_binary(
        config=MobileGatewayConfig(push_provider="test"),
        resolve_gateway_command=lambda: (),
    )

    assert check.status == "WARN"
    assert (
        check.summary
        == "mobile gateway is configured but no sase_gateway command resolves"
    )
    assert "sase-core target/debug" in check.details[0]
    assert any("cargo build -p sase_gateway" in step for step in check.next_steps)
    assert check.data["mobile_configured"] is True
    assert check.data["push_enabled"] is True
    assert check.data["command_resolved"] is False
    assert check.data["resolver"] == "sase_gateway"


def test_mobile_gateway_binary_ok_when_default_resolver_finds_gateway() -> None:
    check = _check_mobile_gateway_binary(
        config=MobileGatewayConfig(push_provider="test"),
        resolve_gateway_command=lambda: ("/opt/sase/bin/sase_gateway",),
    )

    assert check.status == "OK"
    assert check.summary == "sase_gateway command resolves for mobile gateway startup"
    assert check.data["command_resolved"] is True
    assert check.data["resolver"] == "sase_gateway"


def test_mobile_gateway_binary_ok_when_configured_command_is_available() -> None:
    check = _check_mobile_gateway_binary(
        config=MobileGatewayConfig(command=("/opt/sase/bin/sase_gateway",)),
        resolve_gateway_command=lambda: (),
        command_head_available=lambda head: head == "/opt/sase/bin/sase_gateway",
    )

    assert check.status == "OK"
    assert check.summary == "configured mobile gateway command is available"
    assert check.data["command_configured"] is True
    assert check.data["command_resolved"] is True
    assert check.data["resolver"] == "configured"


def test_mobile_gateway_binary_warns_when_configured_command_is_missing() -> None:
    check = _check_mobile_gateway_binary(
        config=MobileGatewayConfig(command=("missing-sase-gateway",)),
        resolve_gateway_command=lambda: ("/unused/sase_gateway",),
        command_head_available=lambda _head: False,
    )

    assert check.status == "WARN"
    assert (
        check.summary
        == "mobile gateway is configured but the configured command was not found"
    )
    assert check.details == ("missing command head: missing-sase-gateway",)
    assert any("mobile_gateway.command" in step for step in check.next_steps)
    assert check.data["command_configured"] is True
    assert check.data["command_resolved"] is False
    assert check.data["resolver"] == "configured"
