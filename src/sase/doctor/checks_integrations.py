"""Integration checks for ``sase doctor``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.integrations.mobile_gateway import (
    MobileGatewayConfig,
    load_mobile_gateway_config,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def integration_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return integration check specs."""
    del context
    return (
        CheckSpec(
            id="integrations.mobile_push_config",
            group="integrations",
            title="Mobile push configuration",
            runner=_check_mobile_push_config,
        ),
    )


def _check_mobile_push_config(
    *,
    config: MobileGatewayConfig | None = None,
) -> DiagnosticCheck:
    """Check that enabled mobile push config has enough FCM metadata."""
    config = config or load_mobile_gateway_config()
    data = _mobile_push_config_data(config)

    if config.push_provider == "disabled":
        return DiagnosticCheck(
            id="integrations.mobile_push_config",
            group="integrations",
            status="SKIP",
            title="Mobile push configuration",
            summary="mobile push is disabled",
            data=data,
        )

    if config.push_provider == "test":
        return DiagnosticCheck(
            id="integrations.mobile_push_config",
            group="integrations",
            status="OK",
            title="Mobile push configuration",
            summary="mobile push uses the test provider",
            data=data,
        )

    if config.fcm_dry_run:
        return DiagnosticCheck(
            id="integrations.mobile_push_config",
            group="integrations",
            status="OK",
            title="Mobile push configuration",
            summary="FCM push is configured for dry-run mode",
            data=data,
        )

    missing = _missing_fcm_fields(config)
    if missing:
        return DiagnosticCheck(
            id="integrations.mobile_push_config",
            group="integrations",
            status="ERROR",
            title="Mobile push configuration",
            summary="FCM push is enabled but required config is missing",
            details=tuple(f"missing: {field}" for field in missing),
            next_steps=(
                "Set `mobile_gateway.fcm_project_id` and either `mobile_gateway.fcm_service_account_json` or `mobile_gateway.fcm_credential_env`.",
                "Use `mobile_gateway.fcm_dry_run: true` only when intentionally testing without live FCM credentials.",
            ),
            data=data,
        )

    return DiagnosticCheck(
        id="integrations.mobile_push_config",
        group="integrations",
        status="OK",
        title="Mobile push configuration",
        summary="FCM push configuration has a project ID and credential source",
        data=data,
    )


def _mobile_push_config_data(config: MobileGatewayConfig) -> dict[str, Any]:
    return {
        "push_provider": config.push_provider,
        "push_enabled": config.push_provider != "disabled",
        "fcm_dry_run": config.fcm_dry_run,
        "fcm_project_id_configured": bool(config.fcm_project_id),
        "fcm_service_account_json_configured": (
            config.fcm_service_account_json is not None
        ),
        "fcm_env_var_configured": bool(config.fcm_credential_env),
        "fcm_auth_source_configured": _has_fcm_credential_source(config),
    }


def _missing_fcm_fields(config: MobileGatewayConfig) -> tuple[str, ...]:
    missing: list[str] = []
    if not config.fcm_project_id:
        missing.append("mobile_gateway.fcm_project_id")
    if not _has_fcm_credential_source(config):
        missing.append(
            "mobile_gateway.fcm_service_account_json or mobile_gateway.fcm_credential_env"
        )
    return tuple(missing)


def _has_fcm_credential_source(config: MobileGatewayConfig) -> bool:
    return config.fcm_service_account_json is not None or bool(
        config.fcm_credential_env
    )


__all__ = [
    "integration_check_specs",
]
