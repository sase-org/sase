"""Routing state and diagnostics shared by the LLM registry façade."""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.time import format_local

from ._registry_metadata import provider_path_env_var
from .provider_disable import TemporaryProviderDisable
from .types import LLMInvocationError

ProviderDisableSnapshot = Mapping[str, TemporaryProviderDisable]


@dataclass(frozen=True, slots=True)
class ProviderRoutingStatus:
    """Display-ready routing state for one registered LLM provider."""

    provider: str
    model_count: int
    cli_available: bool
    active_disable: TemporaryProviderDisable | None
    hidden_from_model_pickers: bool
    affected_aliases: tuple[str, ...] = ()


class ProviderTemporarilyDisabledError(LLMInvocationError):
    """Raised before a disabled provider plugin can be instantiated."""

    def __init__(self, provider: str, disable: TemporaryProviderDisable) -> None:
        self.provider = provider
        self.disable = disable
        super().__init__(
            f"LLM provider {provider!r} is temporarily disabled "
            f"{format_provider_disable_expiry(disable)}. "
            "Enable the provider or choose a different model/provider."
        )


def provider_cli_available(
    provider_name: str,
    payload: Mapping[str, Any],
    *,
    environ: Mapping[str, str],
    which: Callable[[str], str | None],
) -> bool:
    """Return whether a registered provider's declared CLI is installed."""
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return False
    metadata = providers.get(provider_name)
    if not isinstance(metadata, dict):
        return False
    cli_name = metadata.get("autodetect_cli_name")
    if cli_name is not None:
        cli_name = str(cli_name).strip() or None
    override = environ.get(provider_path_env_var(provider_name), "").strip()
    command = override or cli_name
    if command is None:
        return True
    expanded = os.path.expanduser(command)
    if which(expanded) is not None:
        return True
    if os.sep in expanded:
        candidate = Path(expanded)
        return candidate.is_file() and os.access(candidate, os.X_OK)
    return False


def provider_model_counts(payload: Mapping[str, object]) -> dict[str, int]:
    """Count known models for each provider in a metadata payload."""
    providers = payload.get("providers")
    model_to_provider = payload.get("model_to_provider")
    counts: dict[str, int] = {}
    if isinstance(model_to_provider, dict):
        for provider in model_to_provider.values():
            counts[str(provider)] = counts.get(str(provider), 0) + 1
    if isinstance(providers, dict):
        for provider, metadata in providers.items():
            if provider in counts or not isinstance(metadata, dict):
                continue
            models = metadata.get("known_model_names")
            counts[str(provider)] = len(models) if isinstance(models, list) else 0
    return counts


def affected_aliases_by_provider() -> dict[str, tuple[str, ...]]:
    """Return configured model aliases associated with each provider."""
    try:
        from .alias_view import build_alias_views

        views = build_alias_views(provider_disables={})
    except Exception:
        return {}

    affected: dict[str, set[str]] = {}
    for view in views:
        providers: set[str] = set()
        if view.provider:
            providers.add(view.provider)
        if view.override is not None:
            providers.add(view.override.provider)
        for member in view.selector_members:
            if member.provider:
                providers.add(member.provider)
        for provider in providers:
            affected.setdefault(provider, set()).add(view.name)
    return {
        provider: tuple(sorted(alias_names))
        for provider, alias_names in affected.items()
    }


def format_provider_model_label(
    llm_provider: str | None = None,
    model: str | None = None,
) -> str:
    """Format provider and model as ``PROVIDER(model)``."""
    if llm_provider and model:
        return f"{llm_provider.upper()}({model})"
    if llm_provider:
        return llm_provider.upper()
    if model:
        return model
    return "Agent"


def format_provider_disable_expiry(
    disable: TemporaryProviderDisable,
    *,
    now: float | None = None,
) -> str:
    """Format a provider-disable expiry for non-TUI diagnostics."""
    if disable.expires_at is None:
        return "until cleared"
    expires = format_local(disable.expires_at, "%Y-%m-%d %H:%M:%S %Z")
    current = datetime.now(tz=UTC).timestamp() if now is None else now
    remaining = max(0.0, disable.expires_at - current)
    return f"until {expires} ({_format_duration(remaining)} remaining)"


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
