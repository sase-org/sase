"""LLM provider check registry and shared helpers for ``sase doctor``."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from typing import Any, TYPE_CHECKING

from sase.agent_clis.detect import resolve_executable
from sase.agent_clis.models import InstallMethod
from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.llm_provider import registry as llm_registry
from sase.llm_provider.config import get_llm_provider_config
from sase.llm_provider.temporary_override import get_active_temporary_override

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


_PROVIDER_SETUP_FALLBACKS: dict[str, dict[str, str]] = {
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
    "fakey": {
        "tool": "Fakey",
        "install": "bundled with SASE — nothing to install",
        "auth": "no authentication required",
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
    from sase.doctor.checks_providers_registry import check_llm_registry

    return check_llm_registry()


def _check_llm_default(context: DoctorContext) -> DiagnosticCheck:
    from sase.doctor.checks_providers_default import check_llm_default

    return check_llm_default(context)


def _check_llm_auth(context: DoctorContext) -> DiagnosticCheck:
    from sase.doctor.checks_providers_auth import check_llm_auth

    return check_llm_auth(context)


def selection_context() -> dict[str, Any]:
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


def providers_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return {}
    return {
        str(name): dict(metadata)
        for name, metadata in providers.items()
        if isinstance(metadata, dict)
    }


def metadata_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def provider_readiness_rows(
    providers: dict[str, dict[str, Any]], env: dict[str, str]
) -> list[dict[str, Any]]:
    return [
        provider_readiness(provider_name, providers[provider_name], env)
        for provider_name in sorted(providers)
    ]


def provider_readiness(
    provider_name: str,
    metadata: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    cli_name = optional_str(metadata.get("autodetect_cli_name"))
    env_var = _provider_path_env(provider_name)
    configured_command = optional_str(env.get(env_var))
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
        "setup_hint": setup_hint(provider_name, metadata),
    }


def format_readiness_details(readiness: list[dict[str, Any]]) -> tuple[str, ...]:
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


def format_selection(selection: dict[str, Any]) -> str:
    reason = selection["reason"]
    if reason == "config":
        return f"config (`llm_provider.provider={selection['provider']}`)"
    if reason == "temporary_override":
        source = selection.get("source") or "unknown"
        model = selection.get("model") or "-"
        return f"temporary override ({selection['provider']}/{model}, source={source})"
    return "autodetect"


def setup_hint(
    provider_name: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, str] | None:
    """Build doctor setup guidance from provider install metadata.

    The local fallback keeps auth wording and supports older third-party
    providers that do not yet publish enriched install metadata.
    """
    fallback = _PROVIDER_SETUP_FALLBACKS.get(provider_name)
    raw_install = metadata.get("install") if metadata is not None else None
    install = raw_install if isinstance(raw_install, Mapping) else {}
    tool = optional_str(install.get("display_name"))
    manager = optional_str(install.get("manager"))
    package = optional_str(install.get("package"))
    docs_url = optional_str(install.get("docs_url"))
    if not any((tool, manager, package, docs_url)):
        return dict(fallback) if fallback is not None else None

    if manager == "npm" and package:
        install_text = f"npm install -g {package}"
    elif manager == "bundled":
        install_text = "bundled with SASE — nothing to install"
    elif manager == InstallMethod.SCRIPT:
        install_text = f"run `sase agent-cli install {provider_name}`"
    elif docs_url:
        install_text = f"install from {docs_url}"
    elif fallback is not None:
        install_text = fallback["install"]
    else:
        install_text = f"install the {provider_name} CLI"
    hint = {
        "tool": tool or (fallback or {}).get("tool", provider_name),
        "install": install_text,
        "auth": (fallback or {}).get(
            "auth", f"follow the {provider_name} authentication flow"
        ),
    }
    if docs_url:
        hint["docs_url"] = docs_url
    return hint


def setup_hints_for(providers: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    return {
        name: hint
        for name in sorted(providers)
        if (hint := setup_hint(name, providers[name])) is not None
    }


def format_setup_hint(
    provider_name: str,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    hint = setup_hint(provider_name, metadata)
    if hint is None:
        return f"Install and authenticate the {provider_name} CLI."
    return _format_setup_hint_dict(hint)


def first_provider_setup_step(readiness: list[dict[str, Any]]) -> str:
    for row in readiness:
        hint = row.get("setup_hint")
        if isinstance(hint, dict):
            return _format_setup_hint_dict(hint)
    return "Install and authenticate at least one SASE LLM provider CLI."


def _format_setup_hint_dict(hint: Mapping[str, str]) -> str:
    text = f"{hint['tool']} setup: {hint['install']}; {hint['auth']}."
    docs_url = hint.get("docs_url")
    return f"{text} Docs: {docs_url}" if docs_url else text


def optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _provider_path_env(provider_name: str) -> str:
    # Single canonical derivation lives in the registry so the doctor and the
    # metadata cache policy can never drift on the SASE_<PROVIDER>_PATH name.
    return llm_registry.provider_path_env_var(provider_name)


def _resolve_executable(command: str | None) -> str | None:
    return resolve_executable(command, which_fn=shutil.which)


_selection_context = selection_context
_providers_from_payload = providers_from_payload
_metadata_list = metadata_list
_provider_readiness_rows = provider_readiness_rows
_provider_readiness = provider_readiness
_format_readiness_details = format_readiness_details
_format_selection = format_selection
_setup_hint = setup_hint
_setup_hints_for = setup_hints_for
_format_setup_hint = format_setup_hint
_first_provider_setup_step = first_provider_setup_step
_optional_str = optional_str


__all__ = [
    "provider_check_specs",
]
