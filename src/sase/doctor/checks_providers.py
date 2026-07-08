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
    "agy": {
        "tool": "Antigravity CLI",
        "install": "curl -fsSL https://antigravity.google/cli/install.sh | bash",
        "auth": "run `agy` and complete the login/trust onboarding",
    },
}

_AUTH_NOT_VERIFIED = (
    "auth: not verified (doctor is read-only and does not call provider APIs)"
)
_AUTH_EVIDENCE_ONLY = "auth: offline evidence only; token validity was not verified"
_RERUN_LLM_DEFAULT = "Rerun `sase doctor -C llm.default -v` before `sase run`."
_RERUN_LLM_AUTH = "Rerun `sase doctor -C llm.auth -v` before `sase run`."
_ENV_REF_RE = re.compile(r"\$(\w+)|\$\{([^}]+)\}")


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
        CheckSpec(
            id="llm.auth",
            group="llm",
            title="Default LLM provider auth",
            runner=lambda: _check_llm_auth(context),
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


def _check_llm_auth(context: DoctorContext) -> DiagnosticCheck:
    """Check offline auth evidence for the effective default provider."""
    try:
        payload = llm_registry.get_llm_metadata_payload()
        providers = _providers_from_payload(payload)
    except Exception as exc:  # noqa: BLE001 - report provider metadata failures.
        return DiagnosticCheck(
            id="llm.auth",
            group="llm",
            status="ERROR",
            title="Default LLM provider auth",
            summary="default LLM provider auth could not inspect registry metadata",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=(
                "Run `sase doctor -C llm.registry` and fix provider registry errors first.",
            ),
            data={
                "error": f"{type(exc).__name__}: {exc}",
                "auth_status": "metadata_error",
                "auth_verified": False,
            },
        )

    selection = _selection_context()
    try:
        provider_name = llm_registry.get_default_provider_name()
    except Exception as exc:  # noqa: BLE001 - llm.default owns CLI availability.
        readiness = _provider_readiness_rows(providers, context.env)
        return DiagnosticCheck(
            id="llm.auth",
            group="llm",
            status="SKIP",
            title="Default LLM provider auth",
            summary="default LLM provider CLI is unavailable; auth evidence not checked",
            details=(
                f"selection source: {_format_selection(selection)}",
                f"{type(exc).__name__}: {exc}",
                *_format_readiness_details(readiness),
                _AUTH_EVIDENCE_ONLY,
            ),
            next_steps=(
                "Fix `llm.default` first.",
                _RERUN_LLM_DEFAULT,
            ),
            data={
                "provider": None,
                "selection": selection,
                "selection_source": selection["reason"],
                "registered_providers": sorted(providers),
                "provider_readiness": readiness,
                "auth_status": "skipped_cli_missing",
                "auth_verified": False,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )

    metadata = providers.get(provider_name)
    if metadata is None:
        return DiagnosticCheck(
            id="llm.auth",
            group="llm",
            status="ERROR",
            title="Default LLM provider auth",
            summary=f"default provider {provider_name!r} is not registered",
            next_steps=(
                "Update `llm_provider.provider` in sase.yml or install the matching provider plugin.",
            ),
            data={
                "provider": provider_name,
                "selection": selection,
                "registered_providers": sorted(providers),
                "auth_status": "metadata_error",
                "auth_verified": False,
            },
        )

    selected_readiness = _provider_readiness(provider_name, metadata, context.env)
    command = selected_readiness["command"]
    executable = selected_readiness["executable"]
    cli_required = command is not None
    details: list[str] = [
        f"selected provider: {provider_name}",
        f"selection source: {_format_selection(selection)}",
    ]

    if selected_readiness["configured_command"]:
        details.append(
            f"{selected_readiness['path_env']}: "
            f"{selected_readiness['configured_command']}"
        )
    elif selected_readiness["cli_name"]:
        details.append(f"declared CLI: {selected_readiness['cli_name']}")

    if executable:
        details.append(f"executable path: {executable}")

    if cli_required and executable is None:
        return DiagnosticCheck(
            id="llm.auth",
            group="llm",
            status="SKIP",
            title="Default LLM provider auth",
            summary=(
                f"{provider_name} executable is missing; auth evidence not checked"
            ),
            details=(
                *details,
                f"command {command!r} executable: missing",
                _AUTH_EVIDENCE_ONLY,
            ),
            next_steps=(
                "Fix `llm.default` first.",
                _RERUN_LLM_DEFAULT,
            ),
            data={
                "provider": provider_name,
                "selection": selection,
                "selection_source": selection["reason"],
                "cli_ready": False,
                "provider_readiness": selected_readiness,
                "auth_status": "skipped_cli_missing",
                "auth_verified": False,
                "setup_hint": _setup_hint(provider_name),
            },
        )

    evidence = _collect_auth_evidence(metadata, context)
    details.extend(_format_auth_evidence_details(evidence))
    details.append(_AUTH_EVIDENCE_ONLY)

    found = evidence["found"]
    if found:
        status: CheckStatus = "OK"
        summary = f"{provider_name} CLI is present and offline auth evidence was found"
        next_steps: tuple[str, ...] = ()
        auth_status = "evidence_found"
    else:
        status = "WARN"
        summary = (
            f"{provider_name} CLI is present but no offline auth evidence was found"
        )
        next_steps = (
            _format_setup_hint(provider_name),
            _RERUN_LLM_AUTH,
        )
        auth_status = "missing_evidence"

    return DiagnosticCheck(
        id="llm.auth",
        group="llm",
        status=status,
        title="Default LLM provider auth",
        summary=summary,
        details=tuple(details),
        next_steps=next_steps,
        data={
            "provider": provider_name,
            "selection": selection,
            "selection_source": selection["reason"],
            "cli_ready": executable is not None or not cli_required,
            "auth_status": auth_status,
            "auth_verified": False,
            "evidence_found": bool(found),
            "evidence": found,
            "checked_paths": evidence["checked_paths"],
            "checked_env_vars": evidence["checked_env_vars"],
            "skipped_path_patterns": evidence["skipped_path_patterns"],
            "setup_hint": _setup_hint(provider_name),
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


def _collect_auth_evidence(
    metadata: dict[str, Any],
    context: DoctorContext,
) -> dict[str, Any]:
    auth_metadata = _auth_metadata(metadata.get("auth_evidence"))
    found: list[dict[str, str]] = []
    checked_paths: list[dict[str, Any]] = []
    skipped_path_patterns: list[str] = []

    for pattern in auth_metadata["credential_paths"]:
        path = _expand_evidence_path(pattern, env=context.env, cwd=context.cwd)
        if path is None:
            skipped_path_patterns.append(pattern)
            continue
        exists = _path_exists(path)
        checked_paths.append(
            {
                "pattern": pattern,
                "path": str(path),
                "exists": exists,
            }
        )
        if exists:
            found.append(
                {
                    "type": "path",
                    "pattern": pattern,
                    "path": str(path),
                }
            )

    checked_env_vars = tuple(auth_metadata["api_key_env_vars"])
    for env_var in checked_env_vars:
        if _optional_str(context.env.get(env_var)):
            found.append({"type": "env_var", "name": env_var})

    return {
        "found": tuple(found),
        "checked_paths": tuple(checked_paths),
        "checked_env_vars": checked_env_vars,
        "skipped_path_patterns": tuple(skipped_path_patterns),
    }


def _auth_metadata(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        return {"credential_paths": (), "api_key_env_vars": ()}
    return {
        "credential_paths": tuple(
            dict.fromkeys(_metadata_list(value.get("credential_paths")))
        ),
        "api_key_env_vars": tuple(
            dict.fromkeys(_metadata_list(value.get("api_key_env_vars")))
        ),
    }


def _expand_evidence_path(
    pattern: str,
    *,
    env: dict[str, str],
    cwd: Path,
) -> Path | None:
    unresolved = False

    def replace(match: re.Match[str]) -> str:
        nonlocal unresolved
        name = match.group(1) or match.group(2) or ""
        value = env.get(name)
        if value is None:
            unresolved = True
            return match.group(0)
        return value

    expanded = _ENV_REF_RE.sub(replace, pattern)
    if unresolved:
        return None

    if expanded == "~" or expanded.startswith("~/"):
        home = _optional_str(env.get("HOME"))
        if home:
            expanded = f"{home}{expanded[1:]}"
        else:
            expanded = os.path.expanduser(expanded)
    else:
        expanded = os.path.expanduser(expanded)

    path = Path(expanded)
    if not path.is_absolute():
        path = cwd / path
    return path


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _format_auth_evidence_details(evidence: dict[str, Any]) -> tuple[str, ...]:
    found = evidence["found"]
    if found:
        return tuple(f"evidence: {_format_evidence_item(item)}" for item in found)

    details: list[str] = []
    checked_paths = evidence["checked_paths"]
    checked_env_vars = evidence["checked_env_vars"]
    if checked_paths:
        details.append(
            "checked auth paths: "
            + ", ".join(str(item["path"]) for item in checked_paths)
        )
    if checked_env_vars:
        details.append("checked auth env vars: " + ", ".join(checked_env_vars))
    if evidence["skipped_path_patterns"]:
        details.append(
            "skipped auth path patterns with unset env vars: "
            + ", ".join(evidence["skipped_path_patterns"])
        )
    if not details:
        details.append("provider declares no offline auth evidence metadata")
    return tuple(details)


def _format_evidence_item(item: dict[str, str]) -> str:
    if item["type"] == "env_var":
        return f"environment variable {item['name']} is set"
    return f"path exists at {item['path']}"


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
    # Single canonical derivation lives in the registry so the doctor and the
    # metadata cache policy can never drift on the SASE_<PROVIDER>_PATH name.
    return llm_registry.provider_path_env_var(provider_name)


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
