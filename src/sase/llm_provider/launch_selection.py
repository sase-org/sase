"""The authoritative provider/model/effort choice for LLM launch routing.

For pooled model aliases (for example ``@large``), the runner bootstrap
reserves a cursor slot and publishes that selection in ``agent_meta.json``.
The first prompt step redeems the reservation before invoking the provider;
later prompt steps resolve fresh and consume their own cursor slots.

:func:`sase.llm_provider.invoke_agent` accepts an already-resolved
:class:`LaunchSelection` so the caller that owns selection can hand that exact
provider/model/effort choice to the provider call instead of triggering a
second, independent resolution.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.xprompt.directives import PromptDirectives

from .load_balancing import MemberAvailability
from .model_alias_resolution_types import (
    resolved_target_availability,
    resolved_target_is_available,
)
from .provider_disable import TemporaryProviderDisable, get_active_provider_disables
from .types import ModelTier

logger = logging.getLogger(__name__)

ALIAS_ORIGIN_DIRECTIVE = "directive"
ALIAS_ORIGIN_DEFAULT_MODEL = "default_model"
ALIAS_ORIGIN_NONE = "none"

__all__ = [
    "ALIAS_ORIGIN_DEFAULT_MODEL",
    "ALIAS_ORIGIN_DIRECTIVE",
    "ALIAS_ORIGIN_NONE",
    "LaunchSelection",
    "launch_selection_from_reservation",
    "reservation_from_launch_selection",
    "resolve_launch_selection",
]

ProviderDisableSnapshot = Mapping[str, TemporaryProviderDisable]


@dataclass(frozen=True, slots=True)
class LaunchSelection:
    """The concrete provider/model/effort chosen for one agent invocation."""

    provider: str
    model: str
    reasoning_effort: str | None
    effort_explicit: bool
    alias_trail: tuple[str, ...] = ()
    alias_origin: str = ALIAS_ORIGIN_NONE
    cursor_alias: str | None = None


def reservation_from_launch_selection(
    selection: LaunchSelection,
    *,
    alias: str | None,
) -> dict[str, Any]:
    """Return the persisted reservation shape for *selection*."""
    return {
        "alias": alias,
        "target": f"{selection.provider}/{selection.model}",
        "effort": selection.reasoning_effort,
        "alias_trail": list(selection.alias_trail),
        "alias_origin": selection.alias_origin,
        "redeemed": False,
    }


def launch_selection_from_reservation(
    reservation: object,
    *,
    directives: PromptDirectives,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> LaunchSelection | None:
    """Return the reserved selection when it still applies and is routable."""
    if not isinstance(reservation, Mapping):
        return None
    if reservation.get("redeemed") is not False:
        return None
    alias = reservation.get("alias")
    if not isinstance(alias, str) or not alias:
        return None
    target = reservation.get("target")
    if not isinstance(target, str) or "/" not in target:
        return None
    provider, model = target.split("/", 1)
    if not provider or not model:
        return None
    effort = reservation.get("effort")
    if effort is not None and not isinstance(effort, str):
        return None
    alias_trail = reservation.get("alias_trail")
    if not isinstance(alias_trail, list) or not all(
        isinstance(item, str) and item for item in alias_trail
    ):
        return None
    alias_origin = reservation.get("alias_origin")
    if not isinstance(alias_origin, str):
        return None

    current = resolve_launch_selection(
        directives,
        directives.model_alias_overrides,
        consume=False,
        provider_disables=provider_disables,
    )
    if current is None:
        return None
    trail = tuple(alias_trail)
    if (
        current.cursor_alias != alias
        or current.alias_trail != trail
        or current.alias_origin != alias_origin
    ):
        return None

    available = resolved_target_is_available(
        target,
        provider_disables=provider_disables,
    )
    state = resolved_target_availability(
        target,
        provider_disables,
        available=available,
    )
    if state == MemberAvailability.UNAVAILABLE:
        return None

    return LaunchSelection(
        provider=provider,
        model=model,
        reasoning_effort=effort,
        effort_explicit=current.effort_explicit,
        alias_trail=trail,
        alias_origin=alias_origin,
        cursor_alias=alias,
    )


def resolve_launch_selection(
    directives: PromptDirectives,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    model_tier: ModelTier = "large",
    provider_name: str | None = None,
    consume: bool,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> LaunchSelection | None:
    """Resolve *directives* to a concrete provider/model/effort selection.

    Mirrors ``invoke_agent()``'s no-``provider_name`` resolution order: an
    explicit ``%model`` directive wins, then an explicit *provider_name*, then
    the configured ``llm_provider.default_model`` launch setting (folding in a
    namespaced temporary setting override and shipped ``@large`` default).

    Returns ``None`` only for the edge case where the caller already supplied
    *provider_name* and *directives* carries no ``%model`` directive — there
    is nothing to resolve, and the caller keeps its own model-tier fallback.

    *consume* controls whether a resolved load-balanced alias pool advances
    its cursor; pass ``True`` at most once per real provider invocation.
    """
    from .config import resolve_effective_effort
    from .registry import get_default_provider_name

    overrides = model_alias_overrides or None
    disables = (
        get_active_provider_disables()
        if provider_disables is None
        else provider_disables
    ) or None
    model_override = directives.model
    alias_effort: str | None = None
    alias_trail: tuple[str, ...] = ()
    cursor_alias: str | None = None
    alias_origin = ALIAS_ORIGIN_NONE

    if model_override and not provider_name:
        from .registry import resolve_model_provider_with_cursor

        if disables is None:
            (
                resolved_provider,
                model_override,
                alias_effort,
                alias_trail,
                cursor_alias,
            ) = resolve_model_provider_with_cursor(
                model_override,
                overrides,
                consume=consume,
                model_tier=model_tier,
            )
        else:
            (
                resolved_provider,
                model_override,
                alias_effort,
                alias_trail,
                cursor_alias,
            ) = resolve_model_provider_with_cursor(
                model_override,
                overrides,
                consume=consume,
                model_tier=model_tier,
                provider_disables=disables,
            )
        if alias_trail:
            alias_origin = ALIAS_ORIGIN_DIRECTIVE
        if resolved_provider:
            provider_name = resolved_provider
        elif disables is None:
            provider_name = get_default_provider_name()
            logger.warning(
                "Model override %r did not resolve to an LLM provider; "
                "falling back to default provider %r.",
                directives.model,
                provider_name,
            )
        else:
            provider_name = get_default_provider_name(provider_disables=disables)
            logger.warning(
                "Model override %r did not resolve to an LLM provider; "
                "falling back to default provider %r.",
                directives.model,
                provider_name,
            )

    def _resolve_default_alias() -> tuple[
        str, str, str | None, tuple[str, ...], str | None
    ]:
        from .model_launch_settings import (
            DEFAULT_MODEL_FIELD,
            build_launch_model_setting_snapshot,
        )

        snapshot = build_launch_model_setting_snapshot(
            DEFAULT_MODEL_FIELD,
            overrides,
            model_tier=model_tier,
            consume=consume,
            provider_disables=disables,
        )
        return (
            snapshot.provider,
            snapshot.model,
            snapshot.effort,
            snapshot.alias_trail,
            snapshot.cursor_alias,
        )

    if not model_override and not provider_name:
        provider_name, model_override, alias_effort, alias_trail, cursor_alias = (
            _resolve_default_alias()
        )
        if alias_trail:
            alias_origin = ALIAS_ORIGIN_DEFAULT_MODEL

    if model_override is None or provider_name is None:
        return None

    if not alias_trail:
        alias_origin = ALIAS_ORIGIN_NONE
    effective_effort, effort_explicit = resolve_effective_effort(
        directives, alias_effort
    )
    return LaunchSelection(
        provider=provider_name,
        model=model_override,
        reasoning_effort=effective_effort,
        effort_explicit=effort_explicit,
        alias_trail=alias_trail,
        alias_origin=alias_origin,
        cursor_alias=cursor_alias,
    )
