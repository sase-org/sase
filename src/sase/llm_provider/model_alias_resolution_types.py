"""Types, normalization, and target availability for model-alias resolution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.xprompt.effort import split_model_effort

from .load_balancing import MemberAvailability
from .model_alias_policy import DEFAULT_MODEL_ALIAS_NAME
from .types import ModelTier

if TYPE_CHECKING:
    from .provider_disable import TemporaryProviderDisable

_ALIAS_RESOLUTION_DEPTH_LIMIT = 16

ProviderDisableSnapshot = Mapping[str, "TemporaryProviderDisable"]


def normalize_model_alias_reference(value: str) -> tuple[str | None, str | None]:
    """Return the clean alias name and canonical effort from *value*.

    Only a known trailing effort token is removed. Unknown ``@`` suffixes stay
    attached to the alias name so model identifiers and future syntax are not
    silently reinterpreted.
    """
    clean_value, effort = split_model_effort(value.strip())
    if not clean_value.startswith("@"):
        return None, effort
    alias = clean_value[1:].strip()
    return alias or None, effort


def active_alias_overrides() -> dict[str, Any]:
    """Return active temporary alias overrides, failing safely to none."""
    try:
        from .temporary_override import get_active_alias_overrides

        return get_active_alias_overrides()
    except Exception:
        return {}


def _active_provider_disables() -> dict[str, TemporaryProviderDisable]:
    """Return active provider disables for one routing operation."""
    from .provider_disable import get_active_provider_disables

    return get_active_provider_disables()


def capture_provider_disables(
    provider_disables: ProviderDisableSnapshot | None,
) -> ProviderDisableSnapshot:
    """Return *provider_disables*, or the active snapshot when omitted."""
    if provider_disables is not None:
        return provider_disables
    from . import model_alias_resolution as resolution

    # Prefer the façade name so tests can patch
    # ``model_alias_resolution._active_provider_disables``.
    return getattr(resolution, "_active_provider_disables", _active_provider_disables)()


def resolve_default_alias_target(
    model_tier: ModelTier = "large",
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> str:
    """Return the fallback target for a user-defined ``@default`` alias.

    Only reached when ``default`` is neither temporarily overridden nor
    configured with an explicit target.
    """
    try:
        # Lazy import to avoid an import cycle: registry imports config.
        from .registry import (
            get_configured_default_provider_name,
            get_provider,
            provider_disable_for,
        )

        disables = capture_provider_disables(provider_disables)
        provider_name = get_configured_default_provider_name(provider_disables=disables)
        disable = provider_disable_for(provider_name, disables)
        if disable is not None and disable.is_hard:
            return f"{provider_name}/unknown"
        model = get_provider(
            provider_name,
            provider_disables=disables,
        ).resolve_model_name(model_tier)
        return f"{provider_name}/{model}"
    except Exception:
        return DEFAULT_MODEL_ALIAS_NAME


@dataclass(frozen=True, slots=True)
class ResolvedModelAlias:
    """Concrete target plus config-derived effort and selector provenance."""

    target: str
    effort: str | None = None
    selector_alias: str | None = None
    applied_override: Any | None = None
    suspended_override: Any | None = None
    suspended_provider_disable: TemporaryProviderDisable | None = None
    valid: bool = True
    alias_trail: tuple[str, ...] = ()
    cursor_alias: str | None = None


@dataclass(frozen=True, slots=True)
class ModelAliasSelectorMember:
    """Display/diagnostic information for one alias-selector member."""

    value: str
    target: str
    effort: str | None
    provider: str | None
    available: bool
    valid: bool = True
    selected: bool = False
    weight: int = 1
    sparing: bool = False
    last_resort: bool = False


def provider_for_resolved_target(target: str) -> str | None:
    """Return the explicit or metadata-inferred provider for *target*."""
    from .registry import model_to_provider_map, registered_provider_names

    if "/" in target:
        provider, _ = target.split("/", 1)
        return provider if provider else None
    inferred_provider = model_to_provider_map().get(target)
    return (
        inferred_provider if inferred_provider in registered_provider_names() else None
    )


def resolved_target_is_available(
    target: str,
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> bool:
    """Return whether *target* resolves to a registered, installed provider."""
    from .registry import provider_routing_available

    provider = provider_for_resolved_target(target)
    return provider_routing_available(provider, provider_disables)


def resolved_target_availability(
    target: str,
    provider_disables: ProviderDisableSnapshot | None = None,
    *,
    available: bool,
) -> MemberAvailability:
    """Layer the hard/soft disable mode on top of an already-known bool.

    ``UNAVAILABLE`` when *available* is ``False``; otherwise ``SPARING`` when
    *target*'s provider carries an active soft disable; otherwise
    ``PREFERRED``.
    """
    if not available:
        return MemberAvailability.UNAVAILABLE
    from .registry import provider_disable_for

    provider = provider_for_resolved_target(target)
    disable = provider_disable_for(provider, provider_disables)
    if disable is not None and disable.is_soft:
        return MemberAvailability.SPARING
    return MemberAvailability.PREFERRED


def target_is_available(
    check: Callable[..., bool],
    target: str,
    provider_disables: ProviderDisableSnapshot,
) -> bool:
    """Run *check* with provider-disable kwargs when the callable accepts them."""
    try:
        return check(target, provider_disables=provider_disables)
    except TypeError:
        return check(target)
