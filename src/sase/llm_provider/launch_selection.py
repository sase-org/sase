"""The authoritative provider/model/effort choice for one real LLM invocation.

A pooled model alias (for example ``@large``) advances a machine-global
round-robin cursor exactly once per real launch.
:func:`resolve_launch_selection` is the single place that resolution happens
with ``consume=True``; every other caller (runner metadata preview, step-marker
display, doctor/validation) resolves with ``consume=False`` and never advances
the cursor.

:func:`sase.llm_provider.invoke_agent` accepts an already-resolved
:class:`LaunchSelection` so a caller that consumed the pool once (e.g. the
workflow executor's prompt step) can hand that exact selection to the
provider call instead of triggering a second, independent resolution.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from sase.xprompt.directives import PromptDirectives

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
    from .registry import get_default_provider_name, resolve_model_provider_with_trail
    from .temporary_override import (
        resolve_effective_default_provider_model_with_trail,
    )

    overrides = model_alias_overrides or None
    disables = (
        get_active_provider_disables()
        if provider_disables is None
        else provider_disables
    ) or None
    model_override = directives.model
    alias_effort: str | None = None
    alias_trail: tuple[str, ...] = ()
    alias_origin = ALIAS_ORIGIN_NONE

    if model_override and not provider_name:
        if disables is None:
            resolved_provider, model_override, alias_effort, alias_trail = (
                resolve_model_provider_with_trail(
                    model_override,
                    overrides,
                    consume=consume,
                    model_tier=model_tier,
                )
            )
        else:
            resolved_provider, model_override, alias_effort, alias_trail = (
                resolve_model_provider_with_trail(
                    model_override,
                    overrides,
                    consume=consume,
                    model_tier=model_tier,
                    provider_disables=disables,
                )
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

    def _resolve_default_alias() -> tuple[str, str, str | None, tuple[str, ...]]:
        if disables is None:
            return resolve_effective_default_provider_model_with_trail(
                model_tier,
                overrides,
                consume=consume,
            )
        return resolve_effective_default_provider_model_with_trail(
            model_tier,
            overrides,
            consume=consume,
            provider_disables=disables,
        )

    if not model_override and not provider_name:
        provider_name, model_override, alias_effort, alias_trail = (
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
    )
