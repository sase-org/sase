"""Effective launch default provider/model resolution.

Answers "what runs when a launch names no ``%model``?" by folding the temporary
default-launch setting override into the configured launch model. Kept apart
from :mod:`sase.llm_provider.temporary_override` because this is alias
resolution policy rather than override storage.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from .provider_disable import TemporaryProviderDisable
from .provider_priority import resolve_provider_routing_context
from .types import ModelTier

if TYPE_CHECKING:
    from .provider_priority import ProviderRoutingContext

ProviderDisableSnapshot = Mapping[str, TemporaryProviderDisable]


def resolve_effective_default_provider_model(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    provider_disables: ProviderDisableSnapshot | None = None,
    routing_context: ProviderRoutingContext | None = None,
) -> tuple[str, str]:
    """Return the ``(provider_name, model_name)`` to use for new launches.

    Precedence for a launch with no explicit ``%model`` directive is owned by
    :func:`sase.llm_provider.model_launch_settings.build_launch_model_setting_snapshot`:
    a namespaced temporary setting override wins, then the merged
    ``llm_provider.default_model`` field resolves through the normal alias and
    provider machinery, falling back to the shipped ``@large`` default if the
    field is missing or malformed.
    """
    context = resolve_provider_routing_context(
        provider_disables=provider_disables,
        routing_context=routing_context,
    )
    from .model_launch_settings import resolve_default_launch_provider_model

    return resolve_default_launch_provider_model(
        model_tier,
        model_alias_overrides,
        consume=consume,
        routing_context=context,
    )


def resolve_effective_default_provider_model_with_effort(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    provider_disables: ProviderDisableSnapshot | None = None,
    routing_context: ProviderRoutingContext | None = None,
) -> tuple[str, str, str | None]:
    """Resolve the effective launch default including alias-borne effort."""
    provider, model, effort, _alias_trail = (
        resolve_effective_default_provider_model_with_trail(
            model_tier,
            model_alias_overrides,
            consume=consume,
            provider_disables=provider_disables,
            routing_context=routing_context,
        )
    )
    return provider, model, effort


def resolve_effective_default_provider_model_with_trail(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    provider_disables: ProviderDisableSnapshot | None = None,
    routing_context: ProviderRoutingContext | None = None,
) -> tuple[str, str, str | None, tuple[str, ...]]:
    """Resolve the effective launch default including alias-hop provenance."""
    context = resolve_provider_routing_context(
        provider_disables=provider_disables,
        routing_context=routing_context,
    )
    from .model_launch_settings import resolve_default_launch_provider_model_with_trail

    return resolve_default_launch_provider_model_with_trail(
        model_tier,
        model_alias_overrides,
        consume=consume,
        routing_context=context,
    )
