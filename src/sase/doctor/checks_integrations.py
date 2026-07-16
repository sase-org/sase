"""Integration checks for ``sase doctor``."""

from __future__ import annotations

import shlex
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.config import load_merged_config
from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.integrations.mobile_gateway import (
    DEFAULT_BIND_ADDRESS,
    DEFAULT_PORT,
    DEFAULT_STARTUP_TIMEOUT_SECONDS,
    MobileGatewayConfig,
    load_mobile_gateway_config,
    resolve_gateway_command as default_resolve_gateway_command,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

GatewayCommandResolver = Callable[[], tuple[str, ...]]
CommandHeadProbe = Callable[[str], bool]


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
        CheckSpec(
            id="integrations.telegram_commands",
            group="integrations",
            title="Telegram command executables",
            runner=_check_telegram_commands,
        ),
        CheckSpec(
            id="integrations.mobile_gateway_binary",
            group="integrations",
            title="Mobile gateway binary",
            runner=_check_mobile_gateway_binary,
            deep=True,
        ),
    )


def _check_telegram_commands(
    *,
    config: dict[str, Any] | None = None,
    command_head_available: CommandHeadProbe | None = None,
) -> DiagnosticCheck:
    """Check that every configured Telegram command executable resolves."""
    config = load_merged_config() if config is None else config
    command_head_available = command_head_available or _command_head_available
    telegram = config.get("telegram")
    commands = telegram.get("commands") if isinstance(telegram, dict) else None

    if not isinstance(commands, dict) or not commands:
        return DiagnosticCheck(
            id="integrations.telegram_commands",
            group="integrations",
            status="SKIP",
            title="Telegram command executables",
            summary="no custom Telegram commands are configured",
            data={
                "configured_commands": 0,
                "resolved_commands": 0,
                "unresolved_commands": 0,
                "command_results": (),
            },
        )

    results: list[dict[str, Any]] = []
    details: list[str] = []
    for name, command_config in sorted(commands.items()):
        run = command_config.get("run") if isinstance(command_config, dict) else None
        command_head = _telegram_command_head(run)
        resolved = command_head is not None and command_head_available(command_head)
        displayed_head = command_head or "<invalid run>"
        details.append(
            f"{name}: {displayed_head} ({'resolved' if resolved else 'not found'})"
        )
        results.append(
            {
                "name": name,
                "command_head": command_head,
                "resolved": resolved,
            }
        )

    resolved_count = sum(bool(result["resolved"]) for result in results)
    unresolved_count = len(results) - resolved_count
    data = {
        "configured_commands": len(results),
        "resolved_commands": resolved_count,
        "unresolved_commands": unresolved_count,
        "command_results": results,
    }
    if unresolved_count:
        return DiagnosticCheck(
            id="integrations.telegram_commands",
            group="integrations",
            status="WARN",
            title="Telegram command executables",
            summary=(
                f"{unresolved_count} of {len(results)} custom Telegram command "
                "executables do not resolve"
            ),
            details=details,
            next_steps=(
                "Install each missing executable or update its `telegram.commands.<name>.run` setting.",
            ),
            data=data,
        )

    return DiagnosticCheck(
        id="integrations.telegram_commands",
        group="integrations",
        status="OK",
        title="Telegram command executables",
        summary=f"all {len(results)} custom Telegram command executables resolve",
        details=details,
        data=data,
    )


def _telegram_command_head(run: object) -> str | None:
    if not isinstance(run, str):
        return None
    try:
        argv = shlex.split(run)
    except ValueError:
        return None
    return argv[0] if argv else None


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


def _check_mobile_gateway_binary(
    *,
    config: MobileGatewayConfig | None = None,
    resolve_gateway_command: GatewayCommandResolver = default_resolve_gateway_command,
    command_head_available: CommandHeadProbe | None = None,
) -> DiagnosticCheck:
    """Check that configured mobile gateway usage has a gateway binary."""
    config = config or load_mobile_gateway_config()
    command_head_available = command_head_available or _command_head_available
    data = _mobile_gateway_binary_data(config)

    if not data["mobile_configured"]:
        return DiagnosticCheck(
            id="integrations.mobile_gateway_binary",
            group="integrations",
            status="SKIP",
            title="Mobile gateway binary",
            summary="mobile gateway is not configured",
            data=data,
        )

    if config.command:
        command_head = config.command[0]
        available = command_head_available(command_head)
        data = {**data, "command_resolved": available, "resolver": "configured"}
        if available:
            return DiagnosticCheck(
                id="integrations.mobile_gateway_binary",
                group="integrations",
                status="OK",
                title="Mobile gateway binary",
                summary="configured mobile gateway command is available",
                data=data,
            )
        return DiagnosticCheck(
            id="integrations.mobile_gateway_binary",
            group="integrations",
            status="WARN",
            title="Mobile gateway binary",
            summary="mobile gateway is configured but the configured command was not found",
            details=(f"missing command head: {command_head}",),
            next_steps=(
                "Build or install the Rust `sase_gateway` binary.",
                "Set `mobile_gateway.command` to the executable path or put `sase_gateway` on PATH.",
            ),
            data=data,
        )

    resolved_command = resolve_gateway_command()
    available = bool(resolved_command)
    data = {**data, "command_resolved": available, "resolver": "sase_gateway"}
    if available:
        return DiagnosticCheck(
            id="integrations.mobile_gateway_binary",
            group="integrations",
            status="OK",
            title="Mobile gateway binary",
            summary="sase_gateway command resolves for mobile gateway startup",
            data=data,
        )

    return DiagnosticCheck(
        id="integrations.mobile_gateway_binary",
        group="integrations",
        status="WARN",
        title="Mobile gateway binary",
        summary="mobile gateway is configured but no sase_gateway command resolves",
        details=(
            "Checked PATH and the sibling sase-core target/debug and target/release gateway locations.",
        ),
        next_steps=(
            "Build the Rust gateway with `cargo build -p sase_gateway --manifest-path ../sase-core/Cargo.toml`.",
            "Put `sase_gateway` on PATH or set `mobile_gateway.command` to the executable path.",
        ),
        data=data,
    )


def _mobile_gateway_binary_data(config: MobileGatewayConfig) -> dict[str, Any]:
    return {
        "mobile_configured": _mobile_gateway_configured(config),
        "command_configured": bool(config.command),
        "agent_bridge_configured": bool(config.agent_bridge_command),
        "helper_bridge_configured": bool(config.helper_bridge_command),
        "push_enabled": config.push_provider != "disabled",
        "fcm_configured": bool(
            config.fcm_project_id
            or config.fcm_service_account_json is not None
            or config.fcm_credential_env
            or config.fcm_dry_run
        ),
        "state_dir_configured": config.state_dir is not None,
        "non_default_bind": config.bind_address != DEFAULT_BIND_ADDRESS,
        "non_default_port": config.port != DEFAULT_PORT,
        "allow_non_loopback": config.allow_non_loopback,
        "non_default_timeouts": (
            config.push_timeout_seconds != 5.0
            or config.push_retry_limit != 1
            or config.startup_timeout_seconds != DEFAULT_STARTUP_TIMEOUT_SECONDS
        ),
        "command_resolved": False,
        "resolver": "none",
    }


def _mobile_gateway_configured(config: MobileGatewayConfig) -> bool:
    return any(
        (
            config.command,
            config.agent_bridge_command,
            config.helper_bridge_command,
            config.push_provider != "disabled",
            config.fcm_project_id,
            config.fcm_service_account_json is not None,
            config.fcm_credential_env,
            config.fcm_dry_run,
            config.state_dir is not None,
            config.bind_address != DEFAULT_BIND_ADDRESS,
            config.port != DEFAULT_PORT,
            config.allow_non_loopback,
            config.push_timeout_seconds != 5.0,
            config.push_retry_limit != 1,
            config.startup_timeout_seconds != DEFAULT_STARTUP_TIMEOUT_SECONDS,
        )
    )


def _command_head_available(command_head: str) -> bool:
    head = (
        str(Path(command_head).expanduser())
        if command_head.startswith("~")
        else command_head
    )
    return shutil.which(head) is not None


__all__ = [
    "integration_check_specs",
]
