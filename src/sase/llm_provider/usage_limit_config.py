"""Usage-limit detection configuration for LLM providers.

Deliberately parallel to ``retry_config.py``: built-in defaults are supplied
per-provider via a pluggy hook, user config merges on top, and list fields are
additive with dedup unless a provider opts into ``replace_patterns``.

Types, matching, and reset-hint parsing live in sibling modules and are
re-exported here to preserve the import and monkeypatch surface.
"""

from __future__ import annotations

import time
from typing import Any

from sase.config import load_merged_config

from .usage_limit_config_parse import (
    find_matching_pattern as find_matching_pattern,
    is_usage_limit_error as is_usage_limit_error,
    normalize_for_match as normalize_for_match,
    parse_reset_hint as parse_reset_hint,
)
from .usage_limit_config_types import (
    ProviderUsageLimitConfig as ProviderUsageLimitConfig,
    UsageLimitDetection as UsageLimitDetection,
    UsageLimitSettings as UsageLimitSettings,
)

_MAX_MESSAGE_LEN = 500


def _dedup_ordered(items: list[str]) -> list[str]:
    """Return a list with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _clone_config(cfg: ProviderUsageLimitConfig) -> ProviderUsageLimitConfig:
    """Return a defensive copy so callers can't mutate module-level built-ins."""
    return ProviderUsageLimitConfig(
        patterns=list(cfg.patterns),
        exclude_patterns=list(cfg.exclude_patterns),
        disable_seconds=cfg.disable_seconds,
        honor_reset_hint=cfg.honor_reset_hint,
    )


def _built_in_defaults() -> dict[str, ProviderUsageLimitConfig]:
    """Aggregate ``llm_default_usage_limit_config()`` values from plugins."""
    from .registry import iter_plugins

    defaults: dict[str, ProviderUsageLimitConfig] = {}
    for name, plugin in iter_plugins():
        method = getattr(plugin, "llm_default_usage_limit_config", None)
        if method is None:
            continue
        try:
            config = method()
        except Exception:
            continue
        if config is not None:
            defaults[name] = config
    return defaults


def _load_llm_usage_limit_section() -> dict[str, Any]:
    try:
        data = load_merged_config()
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    llm_config = data.get("llm_provider", {}) or {}
    if not isinstance(llm_config, dict):
        return {}
    usage_limit_section = llm_config.get("usage_limit", {}) or {}
    if not isinstance(usage_limit_section, dict):
        return {}
    return usage_limit_section


def _load_user_provider_dict(provider_name: str) -> dict[str, Any] | None:
    """Return the raw user-configured usage-limit dict for a provider, or None."""
    providers_section = _load_llm_usage_limit_section().get("providers", {}) or {}
    if not isinstance(providers_section, dict):
        return None
    provider_dict = providers_section.get(provider_name)
    if not provider_dict or not isinstance(provider_dict, dict):
        return None
    return provider_dict


def _config_from_user_dict(user_dict: dict[str, Any]) -> ProviderUsageLimitConfig:
    return ProviderUsageLimitConfig(
        patterns=list(user_dict.get("patterns", [])),
        exclude_patterns=list(user_dict.get("exclude_patterns", [])),
        disable_seconds=user_dict.get("disable_seconds"),
        honor_reset_hint=user_dict.get("honor_reset_hint"),
    )


def _merge_with_built_in(
    user_dict: dict[str, Any], built_in: ProviderUsageLimitConfig
) -> ProviderUsageLimitConfig:
    # ``replace_patterns: true`` plus a present ``patterns`` key is a literal
    # replacement, including ``patterns: []``. Key absence still keeps the
    # built-ins so a provider can opt into replacement later without wiping
    # detection in the meantime.
    if user_dict.get("replace_patterns", False) and "patterns" in user_dict:
        patterns = list(user_dict.get("patterns") or [])
    elif user_dict.get("replace_patterns", False):
        patterns = list(built_in.patterns)
    else:
        patterns = _dedup_ordered(
            list(built_in.patterns) + list(user_dict.get("patterns", []))
        )

    # exclude_patterns are always additive; there is no replace escape hatch.
    exclude_patterns = _dedup_ordered(
        list(built_in.exclude_patterns) + list(user_dict.get("exclude_patterns", []))
    )

    # disable_seconds and honor_reset_hint use key-presence checks so that an
    # explicit user null/False overrides a built-in non-null value.
    disable_seconds = (
        user_dict["disable_seconds"]
        if "disable_seconds" in user_dict
        else built_in.disable_seconds
    )
    honor_reset_hint = (
        user_dict["honor_reset_hint"]
        if "honor_reset_hint" in user_dict
        else built_in.honor_reset_hint
    )
    return ProviderUsageLimitConfig(
        patterns=patterns,
        exclude_patterns=exclude_patterns,
        disable_seconds=disable_seconds,
        honor_reset_hint=honor_reset_hint,
    )


def get_usage_limit_config(provider_name: str) -> ProviderUsageLimitConfig | None:
    """Load usage-limit config for a specific provider.

    Merges user-configured values (from
    ``llm_provider.usage_limit.providers.<provider>``) on top of module-level
    built-in defaults supplied by each provider plugin. Returns None if
    neither a user config nor a built-in exists for the provider.
    """
    user_dict = _load_user_provider_dict(provider_name)
    built_in = _built_in_defaults().get(provider_name)

    if user_dict is None and built_in is None:
        return None
    if user_dict is None:
        assert built_in is not None
        return _clone_config(built_in)
    if built_in is None:
        return _config_from_user_dict(user_dict)
    return _merge_with_built_in(user_dict, built_in)


def get_usage_limit_settings() -> UsageLimitSettings:
    """Load the resolved global usage-limit settings."""
    section = _load_llm_usage_limit_section()
    defaults = UsageLimitSettings()
    return UsageLimitSettings(
        enabled=bool(section.get("enabled", defaults.enabled)),
        disable_seconds=int(section.get("disable_seconds", defaults.disable_seconds)),
        min_disable_seconds=int(
            section.get("min_disable_seconds", defaults.min_disable_seconds)
        ),
        max_disable_seconds=int(
            section.get("max_disable_seconds", defaults.max_disable_seconds)
        ),
        honor_reset_hint=bool(
            section.get("honor_reset_hint", defaults.honor_reset_hint)
        ),
        notify=bool(section.get("notify", defaults.notify)),
    )


def _truncate(text: str, max_len: int = _MAX_MESSAGE_LEN) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


# --- Detection ---


def detect_usage_limit(
    provider: str, error_text: str, *, now: float | None = None
) -> UsageLimitDetection | None:
    """Detect a usage-limit failure and resolve its disable duration.

    Returns None when usage-limit detection is disabled globally, the
    provider has no resolved config, or ``error_text`` does not match.
    """
    settings = get_usage_limit_settings()
    if not settings.enabled:
        return None

    config = get_usage_limit_config(provider)
    if config is None:
        return None

    matched_pattern = find_matching_pattern(error_text, config)
    if matched_pattern is None:
        return None

    resolved_now = time.time() if now is None else now

    honor_reset_hint = (
        config.honor_reset_hint
        if config.honor_reset_hint is not None
        else settings.honor_reset_hint
    )
    disable_seconds: float = (
        config.disable_seconds
        if config.disable_seconds is not None
        else settings.disable_seconds
    )

    reset_hint: str | None = None
    expires_at: float | None = None
    used_reset_hint = False

    if honor_reset_hint:
        parsed_expires_at, parsed_hint = parse_reset_hint(
            error_text, now=resolved_now, allow_unanchored=True
        )
        if parsed_expires_at is not None:
            duration = parsed_expires_at - resolved_now
            duration = min(
                max(duration, settings.min_disable_seconds),
                settings.max_disable_seconds,
            )
            disable_seconds = duration
            expires_at = resolved_now + duration
            reset_hint = parsed_hint
            used_reset_hint = True

    # min/max_disable_seconds only bound a reset-hint-derived duration, which
    # is untrusted provider input; the flat disable_seconds fallback is an
    # admin-chosen value and is used as configured.

    return UsageLimitDetection(
        provider=provider,
        matched_pattern=matched_pattern,
        message=_truncate(normalize_for_match(error_text)),
        raw_message=error_text,
        disable_seconds=disable_seconds,
        expires_at=expires_at,
        reset_hint=reset_hint,
        used_reset_hint=used_reset_hint,
    )


def _usage_limit_provider_order() -> list[str]:
    """Return provider names to try, user-configured first, then built-ins."""
    providers_section = _load_llm_usage_limit_section().get("providers", {}) or {}
    order: list[str] = []
    if isinstance(providers_section, dict):
        order.extend(providers_section.keys())
    order.extend(_built_in_defaults().keys())
    return order


def find_usage_limit_detection_for_error(
    error_output: str, *, now: float | None = None
) -> UsageLimitDetection | None:
    """Find a usage-limit detection that matches the error from any provider.

    Mirrors ``retry_config.find_retry_config_for_error``: iterates
    user-configured providers first (preserving insertion order), then any
    built-in-only providers, and returns the first provider whose config
    matches. Used when the caller does not know which provider actually
    produced the error (e.g. a multi-step workflow that may have invoked
    more than one LLM provider).
    """
    checked: set[str] = set()
    for provider_name in _usage_limit_provider_order():
        if provider_name in checked:
            continue
        checked.add(provider_name)
        try:
            detection = detect_usage_limit(provider_name, error_output, now=now)
        except Exception:
            continue
        if detection is not None:
            return detection
    return None
