"""Default LLM provider auth checks for ``sase doctor``."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_providers import (
    _AUTH_EVIDENCE_ONLY,
    _RERUN_LLM_AUTH,
    _RERUN_LLM_DEFAULT,
    format_readiness_details,
    format_selection,
    format_setup_hint,
    llm_registry,
    metadata_list,
    optional_str,
    provider_readiness,
    provider_readiness_rows,
    providers_from_payload,
    selection_context,
    setup_hint,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


_ENV_REF_RE = re.compile(r"\$(\w+)|\$\{([^}]+)\}")


def check_llm_auth(context: DoctorContext) -> DiagnosticCheck:
    """Check offline auth evidence for the effective default provider."""
    try:
        payload = llm_registry.get_llm_metadata_payload()
        providers = providers_from_payload(payload)
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

    selection = selection_context()
    try:
        provider_name = llm_registry.get_default_provider_name()
    except Exception as exc:  # noqa: BLE001 - llm.default owns CLI availability.
        readiness = provider_readiness_rows(providers, context.env)
        return DiagnosticCheck(
            id="llm.auth",
            group="llm",
            status="SKIP",
            title="Default LLM provider auth",
            summary="default LLM provider CLI is unavailable; auth evidence not checked",
            details=(
                f"selection source: {format_selection(selection)}",
                f"{type(exc).__name__}: {exc}",
                *format_readiness_details(readiness),
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

    selected_readiness = provider_readiness(provider_name, metadata, context.env)
    command = selected_readiness["command"]
    executable = selected_readiness["executable"]
    cli_required = command is not None
    details: list[str] = [
        f"selected provider: {provider_name}",
        f"selection source: {format_selection(selection)}",
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
                "setup_hint": setup_hint(provider_name, metadata),
            },
        )

    evidence = _collect_auth_evidence(metadata, context)
    details.extend(_format_auth_evidence_details(evidence))

    auth_not_required = evidence["auth_not_required"]
    if not auth_not_required:
        details.append(_AUTH_EVIDENCE_ONLY)
    found = evidence["found"]
    status: CheckStatus
    next_steps: tuple[str, ...]
    if auth_not_required:
        status = "OK"
        summary = f"{provider_name} CLI is present and requires no authentication"
        next_steps = ()
        auth_status = "not_required"
    elif found:
        status = "OK"
        summary = f"{provider_name} CLI is present and offline auth evidence was found"
        next_steps = ()
        auth_status = "evidence_found"
    else:
        status = "WARN"
        summary = (
            f"{provider_name} CLI is present but no offline auth evidence was found"
        )
        next_steps = (
            format_setup_hint(provider_name, metadata),
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
            "auth_required": not auth_not_required,
            "evidence_found": bool(found),
            "evidence": found,
            "checked_paths": evidence["checked_paths"],
            "checked_env_vars": evidence["checked_env_vars"],
            "skipped_path_patterns": evidence["skipped_path_patterns"],
            "setup_hint": setup_hint(provider_name, metadata),
        },
    )


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
        if optional_str(context.env.get(env_var)):
            found.append({"type": "env_var", "name": env_var})

    return {
        "auth_not_required": auth_metadata["auth_not_required"],
        "found": tuple(found),
        "checked_paths": tuple(checked_paths),
        "checked_env_vars": checked_env_vars,
        "skipped_path_patterns": tuple(skipped_path_patterns),
    }


def _auth_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "credential_paths": (),
            "api_key_env_vars": (),
            "auth_not_required": False,
        }
    return {
        "credential_paths": tuple(
            dict.fromkeys(metadata_list(value.get("credential_paths")))
        ),
        "api_key_env_vars": tuple(
            dict.fromkeys(metadata_list(value.get("api_key_env_vars")))
        ),
        "auth_not_required": value.get("auth_not_required") is True,
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
        home = optional_str(env.get("HOME"))
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
    if evidence["auth_not_required"]:
        return ("provider declares that authentication is not required",)
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


_check_llm_auth = check_llm_auth
