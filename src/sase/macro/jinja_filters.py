"""Shared Jinja2 filters available to xprompt and workflow prompt bodies."""

from __future__ import annotations

from typing import Any

from jinja2 import Environment


def register_prompt_filters(env: Environment) -> None:
    """Register filters usable from prompt-body Jinja2 templates."""
    env.filters["plan_ref_path"] = _plan_ref_path
    env.filters["provider_disabled"] = _provider_disabled
    env.filters["provider_enabled"] = _provider_enabled


_PROVIDER_DISABLE_MODES = ("any", "hard", "soft")


def _provider_disabled(provider: Any, mode: str = "any") -> bool:
    """Return whether *provider* has an active machine-wide disable.

    Non-string, blank, or syntactically invalid provider ids return ``False``
    rather than raising, so a templating slip cannot claim a provider is down.
    An unknown mode raises ``ValueError`` so authoring typos fail loudly.
    A corrupt state file fails open to ``False``.
    """
    if mode not in _PROVIDER_DISABLE_MODES:
        raise ValueError(f"mode must be one of 'any', 'hard', 'soft', got {mode!r}")
    if not isinstance(provider, str):
        return False
    normalized = provider.strip().lower()
    if not normalized:
        return False

    from sase.llm_provider import provider_disable as provider_state

    if not provider_state.is_provider_id(normalized):
        return False
    try:
        record = provider_state.get_active_provider_disables().get(normalized)
    except (provider_state.ProviderDisableStateError, OSError):
        return False
    if record is None:
        return False
    if mode == "hard":
        return record.is_hard
    if mode == "soft":
        return record.is_soft
    return True


def _provider_enabled(provider: Any, mode: str = "any") -> bool:
    """Return whether *provider* has no active machine-wide disable."""
    return not _provider_disabled(provider, mode)


def _plan_ref_path(value: Any) -> Any:
    """Return the ``YYYYmm/<name>.md`` portion of a plan path or reference."""
    if not isinstance(value, str):
        return value

    from sase.sdd.plan_refs import plan_reference_display_path

    return plan_reference_display_path(value)
