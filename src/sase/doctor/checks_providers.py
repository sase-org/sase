"""LLM provider checks for ``sase doctor``."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.llm_provider import registry as llm_registry
from sase.llm_provider.config import get_llm_provider_config
from sase.llm_provider.temporary_override import get_active_temporary_override

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


_PROVIDER_SETUP_HINTS: dict[str, dict[str, str]] = {
    "claude": {
        "tool": "Claude Code",
        "install": "npm install -g @anthropic-ai/claude-code",
        "auth": "run `claude` and complete the login flow",
    },
    "codex": {
        "tool": "Codex CLI",
        "install": "npm install -g @openai/codex",
        "auth": "run `codex login`",
    },
    "gemini": {
        "tool": "Gemini CLI",
        "install": "npm install -g @google/gemini-cli",
        "auth": "run `gemini` and complete the login flow",
    },
    "opencode": {
        "tool": "OpenCode",
        "install": "install from https://opencode.ai/docs",
        "auth": "run `opencode auth login`",
    },
    "qwen": {
        "tool": "Qwen Code",
        "install": "npm install -g @qwen-code/qwen-code",
        "auth": "run `qwen` and complete the login flow",
    },
}

_AUTH_NOT_VERIFIED = (
    "auth: not verified (doctor is read-only and does not call provider APIs)"
)
_RERUN_LLM_DEFAULT = "Rerun `sase doctor -C llm.default -v` before `sase run`."


def provider_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default LLM provider check specs."""
    return (
        CheckSpec(
            id="llm.registry",
            group="llm",
            title="LLM provider registry",
            runner=_check_llm_registry,
        ),
        CheckSpec(
            id="llm.default",
            group="llm",
            title="Default LLM provider",
            runner=lambda: _check_llm_default(context),
        ),
    )


def _check_llm_registry() -> DiagnosticCheck:
    """Verify provider plugin metadata can be loaded."""
    try:
        payload = llm_registry.get_llm_metadata_payload()
    except Exception as exc:  # noqa: BLE001 - doctor converts registry failures.
        return DiagnosticCheck(
            id="llm.registry",
            group="llm",
            status="ERROR",
            title="LLM provider registry",
            summary="LLM provider metadata could not be loaded",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=(
                "Reinstall or disable the failing LLM provider plugin, then rerun `sase doctor -C llm.registry`.",
            ),
            data={"error": f"{type(exc).__name__}: {exc}"},
        )

    providers = _providers_from_payload(payload)
    provider_names = sorted(providers)
    if not provider_names:
        return DiagnosticCheck(
            id="llm.registry",
            group="llm",
            status="ERROR",
            title="LLM provider registry",
            summary="no LLM providers are registered",
            next_steps=(
                "Install at least one SASE LLM provider plugin in this environment.",
            ),
            data={"provider_count": 0, "providers": []},
        )

    model_count = sum(
        len(_metadata_list(metadata.get("known_model_names")))
        for metadata in providers.values()
    )
    autodetect_count = len(_metadata_list(payload.get("autodetect_candidates")))
    return DiagnosticCheck(
        id="llm.registry",
        group="llm",
        status="OK",
        title="LLM provider registry",
        summary=(
            f"{len(provider_names)} provider(s), {model_count} known model(s), "
            f"{autodetect_count} autodetect candidate(s)"
        ),
        data={
            "provider_count": len(provider_names),
            "providers": provider_names,
            "model_count": model_count,
            "autodetect_candidates": _metadata_list(
                payload.get("autodetect_candidates")
            ),
        },
    )


def _check_llm_default(context: DoctorContext) -> DiagnosticCheck:
    """Resolve the effective default provider and check its declared CLI."""
    try:
        payload = llm_registry.get_llm_metadata_payload()
        providers = _providers_from_payload(payload)
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

    selection = _selection_context()
    try:
        provider_name = llm_registry.get_default_provider_name()
    except Exception as exc:  # noqa: BLE001 - default resolution is diagnostic.
        readiness = _provider_readiness_rows(providers, context.env)
        return DiagnosticCheck(
            id="llm.default",
            group="llm",
            status="ERROR",
            title="Default LLM provider",
            summary="no usable default LLM provider executable was found",
            details=(
                f"selection source: {_format_selection(selection)}",
                f"{type(exc).__name__}: {exc}",
                *_format_readiness_details(readiness),
                _AUTH_NOT_VERIFIED,
            ),
            next_steps=(
                _first_provider_setup_step(readiness),
                "Or set `llm_provider.provider` in sase.yml and ensure its executable is on PATH or in SASE_<PROVIDER>_PATH.",
                _RERUN_LLM_DEFAULT,
            ),
            data={
                "provider": None,
                "selection": selection,
                "selection_source": selection["reason"],
                "registered_providers": sorted(providers),
                "provider_readiness": readiness,
                "setup_hints": _setup_hints_for(providers),
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

    selected_readiness = _provider_readiness(provider_name, metadata, context.env)
    cli_name = selected_readiness["cli_name"]
    env_var = selected_readiness["path_env"]
    configured_command = selected_readiness["configured_command"]
    command = selected_readiness["command"]
    executable = selected_readiness["executable"]
    cli_required = command is not None
    status: CheckStatus = "OK"
    details: list[str] = [
        f"selected provider: {provider_name}",
        f"selection source: {_format_selection(selection)}",
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
        next_steps.append(_format_setup_hint(provider_name))
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
            "setup_hint": _setup_hint(provider_name),
            "model_resolutions": metadata.get("model_resolutions", {}),
        },
    )


def _selection_context() -> dict[str, Any]:
    override = get_active_temporary_override()
    if override is not None:
        return {
            "reason": "temporary_override",
            "provider": override.provider,
            "model": override.model,
            "source": override.source,
            "expires_at": override.expires_at,
        }

    config = get_llm_provider_config()
    provider = config.get("provider") if isinstance(config, dict) else None
    if provider:
        return {"reason": "config", "provider": str(provider)}
    return {"reason": "autodetect"}


def _providers_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return {}
    return {
        str(name): dict(metadata)
        for name, metadata in providers.items()
        if isinstance(metadata, dict)
    }


def _metadata_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _provider_readiness_rows(
    providers: dict[str, dict[str, Any]], env: dict[str, str]
) -> list[dict[str, Any]]:
    return [
        _provider_readiness(provider_name, providers[provider_name], env)
        for provider_name in sorted(providers)
    ]


def _provider_readiness(
    provider_name: str,
    metadata: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    cli_name = _optional_str(metadata.get("autodetect_cli_name"))
    env_var = _provider_path_env(provider_name)
    configured_command = _optional_str(env.get(env_var))
    command = configured_command or cli_name
    executable = _resolve_executable(command) if command else None
    return {
        "provider": provider_name,
        "cli_name": cli_name,
        "path_env": env_var,
        "configured_command": configured_command,
        "command": command,
        "executable": executable,
        "ready": executable is not None if command else False,
        "setup_hint": _setup_hint(provider_name),
    }


def _format_readiness_details(readiness: list[dict[str, Any]]) -> tuple[str, ...]:
    if not readiness:
        return ()
    return tuple(
        _format_readiness_detail(row)
        for row in readiness
        if row.get("command") is not None
    )


def _format_readiness_detail(row: dict[str, Any]) -> str:
    executable = row.get("executable") or "missing"
    return f"{row['provider']}: command {row['command']!r}, executable: {executable}"


def _format_selection(selection: dict[str, Any]) -> str:
    reason = selection["reason"]
    if reason == "config":
        return f"config (`llm_provider.provider={selection['provider']}`)"
    if reason == "temporary_override":
        source = selection.get("source") or "unknown"
        model = selection.get("model") or "-"
        return f"temporary override ({selection['provider']}/{model}, source={source})"
    return "autodetect"


def _setup_hint(provider_name: str) -> dict[str, str] | None:
    hint = _PROVIDER_SETUP_HINTS.get(provider_name)
    if hint is None:
        return None
    return dict(hint)


def _setup_hints_for(providers: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    return {
        name: hint
        for name in sorted(providers)
        if (hint := _setup_hint(name)) is not None
    }


def _format_setup_hint(provider_name: str) -> str:
    hint = _setup_hint(provider_name)
    if hint is None:
        return f"Install and authenticate the {provider_name} CLI."
    return f"{hint['tool']} setup: {hint['install']}; {hint['auth']}."


def _first_provider_setup_step(readiness: list[dict[str, Any]]) -> str:
    for row in readiness:
        if row.get("setup_hint"):
            return _format_setup_hint(str(row["provider"]))
    return "Install and authenticate at least one SASE LLM provider CLI."


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _provider_path_env(provider_name: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", provider_name).strip("_").upper()
    return f"SASE_{token}_PATH"


def _resolve_executable(command: str | None) -> str | None:
    if not command:
        return None
    expanded = os.path.expanduser(command)
    resolved = shutil.which(expanded)
    if resolved:
        return resolved
    if os.sep in expanded:
        path = Path(expanded)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


__all__ = [
    "provider_check_specs",
]
