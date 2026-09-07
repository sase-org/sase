"""Types, normalization, and target availability for model-alias resolution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sase.xprompt.effort import split_model_effort

from .load_balancing import MemberAvailability
from .model_alias_policy import DEFAULT_MODEL_ALIAS_NAME
from .types import ModelTier

if TYPE_CHECKING:
    from .provider_disable import TemporaryProviderDisable
    from .provider_priority import (
        ProviderAvailability,
        ProviderAvailabilityProvenance,
        ProviderRoutingContext,
        TemporaryProviderPriority,
    )

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


def capture_provider_routing_context(
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
    routing_context: ProviderRoutingContext | None = None,
    now: float | None = None,
) -> ProviderRoutingContext:
    """Return one complete routing context for a resolution operation."""
    if routing_context is not None and provider_disables is not None:
        raise ValueError("pass routing_context or provider_disables, not both")
    if routing_context is not None:
        return routing_context
    if provider_disables is not None:
        from .provider_priority import provider_routing_context_from_parts

        return provider_routing_context_from_parts(
            provider_disables,
            None,
            captured_at=now,
        )
    from . import model_alias_resolution as resolution
    from .provider_disable import get_active_provider_disables
    from .provider_priority import (
        capture_provider_routing_context as _capture_provider_routing_context,
        provider_routing_context_from_parts,
    )

    disable_capture = getattr(
        resolution,
        "_active_provider_disables",
        get_active_provider_disables,
    )
    if disable_capture is not get_active_provider_disables:
        return provider_routing_context_from_parts(
            _call_provider_disables(disable_capture, now),
            None,
            captured_at=now,
        )
    capture = getattr(
        resolution,
        "_active_provider_routing_context",
        _capture_provider_routing_context,
    )
    if now is None:
        return capture()
    try:
        return capture(now)
    except TypeError:
        try:
            return capture()
        except TypeError as exc:
            raise exc from None


def _call_provider_disables(
    capture: Callable[..., ProviderDisableSnapshot],
    now: float | None,
) -> ProviderDisableSnapshot:
    """Call a legacy provider-disable capture hook with tolerant arity."""
    if now is None:
        return capture()
    try:
        return capture(now)
    except TypeError:
        return cast("ProviderDisableSnapshot", capture())


def resolve_default_alias_target(
    model_tier: ModelTier = "large",
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
    routing_context: ProviderRoutingContext | None = None,
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

        context = capture_provider_routing_context(
            provider_disables=provider_disables,
            routing_context=routing_context,
        )
        provider_name = get_configured_default_provider_name(routing_context=context)
        disable = provider_disable_for(provider_name, routing_context=context)
        if disable is not None and disable.is_hard:
            return f"{provider_name}/unknown"
        model = get_provider(
            provider_name,
            routing_context=context,
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
    availability: MemberAvailability = MemberAvailability.PREFERRED
    provenance: tuple[ProviderAvailabilityProvenance, ...] = ()
    actual_disable: TemporaryProviderDisable | None = None
    priority: TemporaryProviderPriority | None = None
    eligible_for_priority: bool = False

    @property
    def priority_backup(self) -> bool:
        """Return whether priority made this member a backup candidate."""
        return "priority_backup" in self.provenance

    @property
    def actual_soft_disabled(self) -> bool:
        """Return whether a real soft disable made this member sparing."""
        return "actual_soft_disable" in self.provenance


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
    routing_context: ProviderRoutingContext | None = None,
) -> bool:
    """Return whether *target* resolves to a registered, installed provider."""
    routing = resolved_target_routing(
        target,
        provider_disables=provider_disables,
        routing_context=routing_context,
        available=None,
    )
    return routing.availability != MemberAvailability.UNAVAILABLE


def resolved_target_routing(
    target: str,
    provider_disables: ProviderDisableSnapshot | None = None,
    *,
    routing_context: ProviderRoutingContext | None = None,
    available: bool | None,
) -> ProviderAvailability:
    """Return Rust-derived effective routing for a resolved target."""
    from .provider_priority import (
        ProviderAvailability,
        classify_provider_availability,
        provider_availability_facts,
    )
    from .registry import provider_routing_facts

    provider = provider_for_resolved_target(target)
    if provider is None:
        return _fallback_target_routing(target, available=available)
    context = capture_provider_routing_context(
        provider_disables=provider_disables,
        routing_context=routing_context,
    )
    facts = provider_routing_facts(provider)
    if available is True:
        facts = provider_availability_facts(
            provider,
            registered=True,
            user_facing=True,
            cli_available=True,
        )
    elif available is False:
        if provider not in context.provider_disables:
            facts = provider_availability_facts(
                provider,
                registered=bool(facts["registered"]),
                user_facing=bool(facts["user_facing"]),
                cli_available=False,
            )
    return classify_provider_availability(context, facts)


def resolved_target_availability(
    target: str,
    provider_disables: ProviderDisableSnapshot | None = None,
    *,
    available: bool,
    routing_context: ProviderRoutingContext | None = None,
) -> MemberAvailability:
    """Return Rust-derived tri-state availability for a resolved target."""
    return resolved_target_routing(
        target,
        provider_disables,
        routing_context=routing_context,
        available=available,
    ).availability


def target_is_available(
    check: Callable[..., bool],
    target: str,
    provider_disables: ProviderDisableSnapshot,
    *,
    routing_context: ProviderRoutingContext | None = None,
) -> bool:
    """Run *check* with routing kwargs when the callable accepts them."""
    try:
        return check(target, routing_context=routing_context)
    except TypeError:
        pass
    try:
        return check(target, provider_disables=provider_disables)
    except TypeError:
        return check(target)


def _fallback_target_routing(
    target: str,
    *,
    available: bool | None,
) -> ProviderAvailability:
    """Classify an unknown-provider terminal without inventing a provider id."""
    from .provider_priority import (
        PROVIDER_AVAILABILITY_WIRE_SCHEMA_VERSION,
        ProviderAvailability,
    )

    provider = target.split("/", 1)[0] if "/" in target else "unknown"
    if not provider:
        provider = "unknown"
    return ProviderAvailability(
        version=PROVIDER_AVAILABILITY_WIRE_SCHEMA_VERSION,
        provider=provider,
        availability=(
            MemberAvailability.UNAVAILABLE
            if available is False
            else MemberAvailability.PREFERRED
        ),
        provenance=(
            ("unregistered",) if available is False else ("ordinary_available",)
        ),
        actual_disable=None,
        priority=None,
        eligible_for_priority=False,
    )
