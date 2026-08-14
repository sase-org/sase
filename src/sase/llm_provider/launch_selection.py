"""The authoritative provider/model/effort choice for one real LLM invocation.

A pooled model alias (``@smarter``, the implicit ``@default`` chain it backs,
...) advances a machine-global round-robin cursor exactly once per real
launch. :func:`resolve_launch_selection` is the single place that resolution
happens with ``consume=True``; every other caller (runner metadata preview,
step-marker display, doctor/validation) resolves with ``consume=False`` and
never advances the cursor.

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

from .types import ModelTier

logger = logging.getLogger(__name__)

__all__ = ["LaunchSelection", "resolve_launch_selection"]


@dataclass(frozen=True, slots=True)
class LaunchSelection:
    """The concrete provider/model/effort chosen for one agent invocation."""

    provider: str
    model: str
    reasoning_effort: str | None
    effort_explicit: bool


def resolve_launch_selection(
    directives: PromptDirectives,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    model_tier: ModelTier = "large",
    provider_name: str | None = None,
    consume: bool,
) -> LaunchSelection | None:
    """Resolve *directives* to a concrete provider/model/effort selection.

    Mirrors ``invoke_agent()``'s historical no-``provider_name`` resolution
    order: an explicit ``%model`` directive wins, then an explicit
    *provider_name*, then the ``@default`` alias (folding in a launch-scoped
    ``default`` alias override, an active temporary override, or the shipped
    default chain, in that order).

    Returns ``None`` only for the edge case where the caller already supplied
    *provider_name* and *directives* carries no ``%model`` directive — there
    is nothing to resolve, and the caller keeps its own model-tier fallback.

    *consume* controls whether a resolved load-balanced alias pool advances
    its cursor; pass ``True`` at most once per real provider invocation.
    """
    from .config import default_model_alias_name, resolve_effective_effort
    from .registry import get_default_provider_name, resolve_model_provider_with_effort
    from .temporary_override import (
        get_active_temporary_override,
        resolve_effective_default_provider_model_with_effort,
    )

    overrides = model_alias_overrides or None
    model_override = directives.model
    alias_effort: str | None = None

    if model_override and not provider_name:
        resolved_provider, model_override, alias_effort = (
            resolve_model_provider_with_effort(
                model_override,
                overrides,
                consume=consume,
            )
        )
        if resolved_provider:
            provider_name = resolved_provider
        else:
            provider_name = get_default_provider_name()
            logger.warning(
                "Model override %r did not resolve to an LLM provider; "
                "falling back to default provider %r.",
                directives.model,
                provider_name,
            )

    if not model_override and not provider_name:
        active = get_active_temporary_override()
        if overrides and default_model_alias_name() in overrides:
            provider_name, model_override, alias_effort = (
                resolve_effective_default_provider_model_with_effort(
                    model_tier,
                    overrides,
                    consume=consume,
                )
            )
        elif active is not None:
            provider_name = active.provider
            model_override = active.model
            alias_effort = active.effort
        else:
            provider_name, model_override, alias_effort = (
                resolve_effective_default_provider_model_with_effort(
                    model_tier,
                    overrides,
                    consume=consume,
                )
            )

    if model_override is None or provider_name is None:
        return None

    effective_effort, effort_explicit = resolve_effective_effort(
        directives, alias_effort
    )
    return LaunchSelection(
        provider=provider_name,
        model=model_override,
        reasoning_effort=effective_effort,
        effort_explicit=effort_explicit,
    )
