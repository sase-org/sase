"""Default LLM provider checks for ``sase doctor``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_providers import (
    _AUTH_NOT_VERIFIED,
    _RERUN_LLM_DEFAULT,
    first_provider_setup_step,
    format_readiness_details,
    format_selection,
    format_setup_hint,
    llm_registry,
    provider_readiness,
    provider_readiness_rows,
    providers_from_payload,
    selection_context,
    setup_hint,
    setup_hints_for,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def check_llm_default(context: DoctorContext) -> DiagnosticCheck:
    """Resolve the effective default provider and check its declared CLI."""
    try:
        payload = llm_registry.get_llm_metadata_payload()
        providers = providers_from_payload(payload)
    except Exception as exc:  # noqa: BLE001 - report provider metadata failures.
        return DiagnosticCheck(
            id="llm.default",
            group="llm",
            status="ERROR",
            title="Default LLM provider",
            summary="default LLM provider could not inspect registry metadata",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=(
                "Run `sase doctor -C llm.registry` and fix provider registry errors first.",
            ),
            data={"error": f"{type(exc).__name__}: {exc}"},
        )

    selection = selection_context()
    try:
        provider_name = llm_registry.get_default_provider_name()
    except Exception as exc:  # noqa: BLE001 - default resolution is diagnostic.
        readiness = provider_readiness_rows(providers, context.env)
        return DiagnosticCheck(
            id="llm.default",
            group="llm",
            status="ERROR",
            title="Default LLM provider",
            summary="no usable default LLM provider executable was found",
            details=(
                f"selection source: {format_selection(selection)}",
                f"{type(exc).__name__}: {exc}",
                *format_readiness_details(readiness),
                _AUTH_NOT_VERIFIED,
            ),
            next_steps=(
                first_provider_setup_step(readiness),
                "Or set `llm_provider.provider` in sase.yml and ensure its executable is on PATH or in SASE_<PROVIDER>_PATH.",
                _RERUN_LLM_DEFAULT,
            ),
            data={
                "provider": None,
                "selection": selection,
                "selection_source": selection["reason"],
                "registered_providers": sorted(providers),
                "provider_readiness": readiness,
                "setup_hints": setup_hints_for(providers),
                "auth_status": "not_verified",
                "auth_verified": False,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )

    metadata = providers.get(provider_name)
    if metadata is None:
        return DiagnosticCheck(
            id="llm.default",
            group="llm",
            status="ERROR",
            title="Default LLM provider",
            summary=f"default provider {provider_name!r} is not registered",
            next_steps=(
                "Update `llm_provider.provider` in sase.yml or install the matching provider plugin.",
            ),
            data={
                "provider": provider_name,
                "selection": selection,
                "registered_providers": sorted(providers),
            },
        )

    selected_readiness = provider_readiness(provider_name, metadata, context.env)
    cli_name = selected_readiness["cli_name"]
    env_var = selected_readiness["path_env"]
    configured_command = selected_readiness["configured_command"]
    command = selected_readiness["command"]
    executable = selected_readiness["executable"]
    cli_required = command is not None
    status: CheckStatus = "OK"
    details: list[str] = [
        f"selected provider: {provider_name}",
        f"selection source: {format_selection(selection)}",
        _AUTH_NOT_VERIFIED,
    ]
    next_steps: list[str] = []

    if configured_command:
        details.append(f"{env_var}: {configured_command}")
    elif cli_name:
        details.append(f"declared CLI: {cli_name}")

    if cli_required and executable is None:
        status = "ERROR"
        summary = (
            f"{provider_name} selected from {selection['reason']}; "
            f"executable {command!r} was not found"
        )
        if configured_command:
            next_steps.append(
                f"Fix `{env_var}` or unset it so PATH autodetection can be used."
            )
        else:
            next_steps.append(
                f"Install the {provider_name} CLI or set `{env_var}` to its executable path."
            )
        next_steps.append(format_setup_hint(provider_name, metadata))
        next_steps.append(_RERUN_LLM_DEFAULT)
    elif executable:
        summary = (
            f"{provider_name} selected from {selection['reason']}; executable found"
        )
        details.append(f"executable path: {executable}")
    else:
        summary = (
            f"{provider_name} selected from {selection['reason']}; "
            "no required CLI metadata declared"
        )

    return DiagnosticCheck(
        id="llm.default",
        group="llm",
        status=status,
        title="Default LLM provider",
        summary=summary,
        details=tuple(details),
        next_steps=tuple(next_steps),
        data={
            "provider": provider_name,
            "selection": selection,
            "selection_source": selection["reason"],
            "ready": status == "OK",
            "cli_required": cli_required,
            "cli_name": cli_name,
            "path_env": env_var,
            "configured_command": configured_command,
            "command": command,
            "executable": executable,
            "auth_status": "not_verified",
            "auth_verified": False,
            "setup_hint": setup_hint(provider_name, metadata),
            "model_resolutions": metadata.get("model_resolutions", {}),
        },
    )


_check_llm_default = check_llm_default
