"""Effective launch default provider/model resolution.

Answers "what runs when a launch names no ``%model``?" by folding the temporary
``default`` override into the ``@default`` alias precedence chain. Kept apart
from :mod:`sase.llm_provider.temporary_override` because this is alias
resolution policy rather than override storage.
"""

from __future__ import annotations

from collections.abc import Mapping

from .config import DEFAULT_MODEL_ALIAS_NAME
from .temporary_override_state import TemporaryLLMOverride
from .types import ModelTier


def resolve_effective_default_provider_model(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
) -> tuple[str, str]:
    """Return the ``(provider_name, model_name)`` to use for new launches.

    Precedence for a launch with no explicit ``%model`` directive:

    1. a launch-family ``default`` alias override;
    2. an active primary temporary override (the user's recent explicit choice);
    3. otherwise the ``@default`` alias — a configured
       ``llm_provider.model_aliases.builtin.default`` target, or the configured/
       autodetected provider's ``resolve_model_name(model_tier)`` default.

    This keeps the temporary override winning the "new launch default" slot
    while routing every no-directive launch through the ``@default`` alias so a
    configured default model is never silently bypassed.
    """
    from .launch_alias_overrides import active_launch_alias_overrides

    launch_overrides = active_launch_alias_overrides(model_alias_overrides)
    if DEFAULT_MODEL_ALIAS_NAME in launch_overrides:
        from .registry import (
            get_configured_default_provider_name,
            resolve_model_provider,
        )

        provider, model = resolve_model_provider(
            "@default",
            launch_overrides,
            consume=consume,
            model_tier=model_tier,
        )
        return provider or get_configured_default_provider_name(), model

    override = _active_default_override()
    if override is not None:
        return override.provider, override.model

    from .registry import resolve_default_alias_provider_model

    return resolve_default_alias_provider_model(
        model_tier,
        launch_overrides,
        consume=consume,
    )


def resolve_effective_default_provider_model_with_effort(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
) -> tuple[str, str, str | None]:
    """Resolve the effective launch default including alias-borne effort."""
    from .launch_alias_overrides import active_launch_alias_overrides

    launch_overrides = active_launch_alias_overrides(model_alias_overrides)
    if DEFAULT_MODEL_ALIAS_NAME in launch_overrides:
        from .registry import (
            get_configured_default_provider_name,
            resolve_model_provider_with_effort,
        )

        provider, model, effort = resolve_model_provider_with_effort(
            "@default",
            launch_overrides,
            consume=consume,
            model_tier=model_tier,
        )
        return provider or get_configured_default_provider_name(), model, effort

    override = _active_default_override()
    if override is not None:
        return override.provider, override.model, override.effort

    from .registry import resolve_default_alias_provider_model_with_effort

    return resolve_default_alias_provider_model_with_effort(
        model_tier,
        launch_overrides,
        consume=consume,
    )


def _active_default_override() -> TemporaryLLMOverride | None:
    """Return the active ``default`` temporary override, if any.

    Imported lazily from the override API module so that module stays the single
    public entry point (and so tests keep patching one place).
    """
    from .temporary_override import get_active_temporary_override

    return get_active_temporary_override()
