"""Node/npm setup readiness checks for ``sase doctor``."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, TYPE_CHECKING

from sase.diagnostics import DiagnosticCheck
from sase.doctor.checks_runtime_common import (
    optional_str,
    resolve_command_from_env,
    which_from_env,
)
from sase.llm_provider import registry as llm_registry

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


MetadataPayloadFn = Callable[[], Mapping[str, Any]]


def check_runtime_node(
    context: DoctorContext,
    *,
    metadata_payload_fn: MetadataPayloadFn | None = None,
) -> DiagnosticCheck:
    """Check Node/npm only when registered provider setup may need npm."""
    node_path = which_from_env(context.env)("node")
    npm_path = which_from_env(context.env)("npm")
    missing_tools = [
        tool
        for tool, executable in (("node", node_path), ("npm", npm_path))
        if executable is None
    ]

    try:
        get_payload = metadata_payload_fn or llm_registry.get_llm_metadata_payload
        payload = get_payload()
        providers = providers_from_payload(payload)
    except Exception as exc:  # noqa: BLE001 - llm.registry owns metadata failures.
        return DiagnosticCheck(
            id="runtime.node",
            group="runtime",
            status="SKIP",
            title="Node/npm setup readiness",
            summary="provider metadata unavailable; node/npm setup not checked",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=(
                "Run `sase doctor -C llm.registry` and fix provider registry errors first.",
            ),
            data={
                "node_path": node_path,
                "npm_path": npm_path,
                "missing_tools": missing_tools,
                "providers": [],
                "missing_provider_clis": [],
                "error": f"{type(exc).__name__}: {exc}",
            },
        )

    npm_providers = npm_provider_readiness_rows(providers, context)
    if not npm_providers:
        return DiagnosticCheck(
            id="runtime.node",
            group="runtime",
            status="SKIP",
            title="Node/npm setup readiness",
            summary="no npm-installed LLM providers are registered",
            data={
                "node_path": node_path,
                "npm_path": npm_path,
                "missing_tools": missing_tools,
                "providers": [],
                "missing_provider_clis": [],
            },
        )

    missing_provider_clis = [
        row["provider"]
        for row in npm_providers
        if row["command"] is not None and row["executable"] is None
    ]
    details = (
        f"node: {node_path or 'missing'}",
        f"npm: {npm_path or 'missing'}",
        *format_npm_provider_details(npm_providers),
    )

    if missing_tools and missing_provider_clis:
        missing_tool_text = "/".join(missing_tools)
        missing_provider_text = ", ".join(missing_provider_clis)
        return DiagnosticCheck(
            id="runtime.node",
            group="runtime",
            status="WARN",
            title="Node/npm setup readiness",
            summary=(
                f"{missing_tool_text} missing while npm-installed provider CLI(s) "
                f"are unavailable: {missing_provider_text}"
            ),
            details=details,
            next_steps=(
                "Install Node.js/npm before following npm-based provider setup instructions.",
                "Install the missing provider CLI(s), then rerun `sase doctor -C runtime.node -v`.",
            ),
            data={
                "node_path": node_path,
                "npm_path": npm_path,
                "missing_tools": missing_tools,
                "providers": npm_providers,
                "missing_provider_clis": missing_provider_clis,
            },
        )

    if missing_tools:
        summary = (
            "node/npm is missing, but registered npm-installed provider CLIs "
            "are already available"
        )
    else:
        summary = "node and npm are available for npm-installed provider setup"

    return DiagnosticCheck(
        id="runtime.node",
        group="runtime",
        status="OK",
        title="Node/npm setup readiness",
        summary=summary,
        details=details,
        data={
            "node_path": node_path,
            "npm_path": npm_path,
            "missing_tools": missing_tools,
            "providers": npm_providers,
            "missing_provider_clis": missing_provider_clis,
        },
    )


def providers_from_payload(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return {}
    return {
        str(provider): dict(metadata)
        for provider, metadata in providers.items()
        if isinstance(metadata, dict)
    }


def npm_provider_readiness_rows(
    providers: Mapping[str, Mapping[str, Any]],
    context: DoctorContext,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for provider_name in sorted(providers):
        metadata = providers[provider_name]
        install = metadata.get("install")
        if not isinstance(install, Mapping) or install.get("manager") != "npm":
            continue

        cli_name = optional_str(metadata.get("autodetect_cli_name"))
        path_env = llm_registry.provider_path_env_var(provider_name)
        configured_command = optional_str(context.env.get(path_env))
        command = configured_command or cli_name
        rows.append(
            {
                "provider": provider_name,
                "manager": "npm",
                "package": optional_str(install.get("package")),
                "scope": optional_str(install.get("scope")),
                "cli_name": cli_name,
                "path_env": path_env,
                "configured_command": configured_command,
                "command": command,
                "executable": resolve_command_from_env(command, context.env),
            }
        )
    return rows


def format_npm_provider_details(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    details: list[str] = []
    for row in rows:
        package = row.get("package") or "unknown package"
        command = row.get("command")
        executable = row.get("executable")
        command_text = repr(command) if command is not None else "not declared"
        executable_text = (executable or "missing") if command is not None else "n/a"
        details.append(
            f"{row['provider']}: {package}; command {command_text}, "
            f"executable: {executable_text}"
        )
    return tuple(details)


__all__ = [
    "check_runtime_node",
    "format_npm_provider_details",
    "llm_registry",
    "npm_provider_readiness_rows",
    "providers_from_payload",
]
