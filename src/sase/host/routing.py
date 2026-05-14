"""Rollout policy helpers for provider-host routing."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal

from sase.config.core import load_config_without_plugin_defaults

HostRoutingMode = Literal["direct", "shadow", "host-preferred", "host-required"]

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}

_LOG = logging.getLogger(__name__)
_ENV_MODE = "SASE_PROVIDER_HOST_MODE"
_LEGACY_ENV_QUERIES = "SASE_PROVIDER_HOST_QUERIES"
_DISABLE_ENV = "SASE_DISABLE_PROVIDER_HOST_ROUTING"

_LOW_RISK_OPERATION_MODES: dict[str, HostRoutingMode] = {
    "llm.metadata": "host-preferred",
    "xprompt.catalog": "host-preferred",
    "vcs.query": "host-preferred",
    "workspace.metadata": "host-preferred",
    "workspace.resolve_ref": "host-preferred",
}

_MODE_ALIASES: dict[str, HostRoutingMode] = {
    "0": "direct",
    "false": "direct",
    "off": "direct",
    "direct": "direct",
    "shadow": "shadow",
    "host_preferred": "host-preferred",
    "host-preferred": "host-preferred",
    "preferred": "host-preferred",
    "daemon": "host-preferred",
    "on": "host-preferred",
    "true": "host-preferred",
    "1": "host-preferred",
    "host_required": "host-required",
    "host-required": "host-required",
    "required": "host-required",
}


@dataclass(frozen=True)
class _ShadowComparison:
    operation: str
    matched: bool
    reason: str


_shadow_comparisons: list[_ShadowComparison] = []


def host_routing_mode(operation: str) -> HostRoutingMode:
    """Return the rollout mode for one provider-host operation."""

    if os.environ.get(_DISABLE_ENV):
        return "direct"
    env_mode = _parse_mode(os.environ.get(_specific_env_name(operation)))
    if env_mode is not None:
        return env_mode
    env_mode = _parse_mode(os.environ.get(_ENV_MODE))
    if env_mode is not None:
        return env_mode
    legacy_queries = _optional_env_bool(_LEGACY_ENV_QUERIES)
    if legacy_queries is not None and operation in _LOW_RISK_OPERATION_MODES:
        return "host-preferred" if legacy_queries else "direct"

    configured = _configured_operation_mode(operation)
    if configured is not None:
        return configured
    return _LOW_RISK_OPERATION_MODES.get(operation, _configured_default_mode())


def host_routing_enabled(operation: str) -> bool:
    return host_routing_mode(operation) in {"shadow", "host-preferred", "host-required"}


def host_required(operation: str) -> bool:
    return host_routing_mode(operation) == "host-required"


def record_shadow_comparison(
    operation: str,
    *,
    direct: Any,
    host: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Record and log the result of a safe shadow comparison."""

    if error is not None:
        comparison = _ShadowComparison(operation, False, type(error).__name__)
        _LOG.warning(
            "provider-host shadow comparison failed for %s: %s",
            operation,
            error,
        )
    else:
        matched = direct == host
        comparison = _ShadowComparison(
            operation,
            matched,
            "match" if matched else "mismatch",
        )
        log = _LOG.debug if matched else _LOG.warning
        log("provider-host shadow comparison %s for %s", comparison.reason, operation)

    _shadow_comparisons.append(comparison)
    if len(_shadow_comparisons) > 100:
        del _shadow_comparisons[: len(_shadow_comparisons) - 100]


def host_routing_diagnostics() -> dict[str, Any]:
    """Return process-local routing policy and recent shadow-comparison state."""

    by_operation: dict[str, str] = {
        operation: host_routing_mode(operation)
        for operation in sorted(_LOW_RISK_OPERATION_MODES)
    }
    configured = _provider_host_config()
    return {
        "default_mode": _configured_default_mode(),
        "low_risk_default_operations": sorted(_LOW_RISK_OPERATION_MODES),
        "operation_modes": by_operation,
        "global_env": os.environ.get(_ENV_MODE),
        "disable_env_set": bool(os.environ.get(_DISABLE_ENV)),
        "shadow_recent": [
            {
                "operation": item.operation,
                "matched": item.matched,
                "reason": item.reason,
            }
            for item in _shadow_comparisons[-20:]
        ],
        "shadow_compare_enabled": bool(configured.get("shadow_compare", True)),
    }


def _configured_operation_mode(operation: str) -> HostRoutingMode | None:
    config = _provider_host_config()
    modes = config.get("modes")
    if not isinstance(modes, dict):
        return None
    return _parse_mode(modes.get(_operation_key(operation)) or modes.get(operation))


def _configured_default_mode() -> HostRoutingMode:
    return _parse_mode(_provider_host_config().get("default_mode")) or "direct"


def _provider_host_config() -> dict[str, Any]:
    daemon_config = load_config_without_plugin_defaults().get("daemon")
    if not isinstance(daemon_config, dict):
        return {}
    provider_host = daemon_config.get("provider_host")
    return provider_host if isinstance(provider_host, dict) else {}


def _parse_mode(value: object) -> HostRoutingMode | None:
    if not isinstance(value, str):
        return None
    return _MODE_ALIASES.get(value.strip().lower().replace("-", "_"))


def _optional_env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _operation_key(operation: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in operation.lower())


def _specific_env_name(operation: str) -> str:
    return f"SASE_PROVIDER_HOST_{_operation_key(operation).upper()}_MODE"


__all__ = [
    "HostRoutingMode",
    "host_required",
    "host_routing_diagnostics",
    "host_routing_enabled",
    "host_routing_mode",
    "record_shadow_comparison",
]
