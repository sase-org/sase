"""Configuration parsing and presentation metadata for model aliases."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from sase.config.core import current_config_token
from sase.xprompt.effort import split_model_effort

from .model_alias_policy import (
    CODER_MODEL_ALIAS_NAME,
    DEFAULT_MODEL_ALIAS_NAME,
    IMPLICIT_ALIAS_TARGETS,
    PROVIDER_CODER_ALIAS_SUFFIX,
    ROLE_ALIAS_DESCRIPTIONS,
    ROLE_ALIAS_FALLBACKS,
)

ModelAliasConfigSource = Literal["builtin", "custom"]


def _llm_provider_config() -> dict[str, Any]:
    """Read config through the compatibility façade.

    Keeping this lookup late-bound preserves callers that patch
    :mod:`sase.llm_provider.config` during diagnostics and tests.
    """
    from . import config

    return config.get_llm_provider_config()


def _raw_model_aliases_config() -> dict[str, Any]:
    """Return the nested ``llm_provider.model_aliases`` object, or ``{}``."""
    value = _llm_provider_config().get("model_aliases", {})
    return value if isinstance(value, dict) else {}


def get_builtin_model_aliases() -> dict[str, str]:
    """Return cleaned ``llm_provider.model_aliases.builtin`` entries."""
    return _clean_string_mapping(_raw_model_aliases_config().get("builtin", {}))


def get_custom_model_aliases() -> dict[str, str]:
    """Return cleaned ``llm_provider.model_aliases.custom`` entries.

    Runtime parsing is deliberately defensive: malformed entries and entries
    with missing or blank ``model`` values are skipped.
    """
    value = _raw_model_aliases_config().get("custom", {})
    if not isinstance(value, dict):
        return {}

    cleaned: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            continue
        alias = key.strip()
        model = item.get("model")
        if not isinstance(model, str):
            continue
        target = model.strip()
        if alias and target:
            cleaned[alias] = target
    return cleaned


def _custom_model_alias_descriptions() -> dict[str, str]:
    """Return configured descriptions for custom aliases that have one."""
    value = _raw_model_aliases_config().get("custom", {})
    if not isinstance(value, dict):
        return {}

    descriptions: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            continue
        alias = key.strip()
        description = item.get("description")
        if not isinstance(description, str):
            continue
        text = description.strip()
        if alias and text:
            descriptions[alias] = text
    return descriptions


def _custom_model_alias_buckets() -> dict[str, str]:
    """Return custom alias-to-bucket membership from configured ``bucket`` tags."""
    value = _raw_model_aliases_config().get("custom", {})
    if not isinstance(value, dict):
        return {}

    buckets: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            continue
        alias = key.strip()
        bucket = item.get("bucket")
        if not isinstance(bucket, str):
            continue
        bucket_name = bucket.strip()
        if alias and bucket_name:
            buckets[alias] = bucket_name
    return buckets


def model_alias_bucket(name: str) -> str | None:
    """Return the Models-panel bucket for custom alias *name*, if configured."""
    alias = name.strip()
    if not alias:
        return None
    return _custom_model_alias_buckets().get(alias)


def model_alias_bucket_description(bucket: str) -> str | None:
    """Return the optional human description for Models-panel *bucket*."""
    bucket_name = bucket.strip()
    if not bucket_name:
        return None
    value = _raw_model_aliases_config().get("buckets", {})
    if not isinstance(value, dict):
        return None
    metadata = value.get(bucket_name)
    if not isinstance(metadata, dict):
        return None
    description = metadata.get("description")
    if not isinstance(description, str):
        return None
    text = description.strip()
    return text or None


def model_alias_bucket_names() -> set[str]:
    """Return bucket names referenced by at least one custom alias."""
    return set(_custom_model_alias_buckets().values())


@lru_cache(maxsize=1)
def get_model_aliases_for_token(_token: tuple[Any, ...]) -> dict[str, str]:
    """Return configured aliases for one merged-config freshness token."""
    return get_builtin_model_aliases() | get_custom_model_aliases()


def get_configured_model_aliases() -> dict[str, str]:
    """Return merged configured aliases; custom aliases win collisions."""
    return get_model_aliases_for_token(current_config_token())


def get_model_aliases() -> dict[str, str]:
    """Return configured model aliases usable from ``%model:<alias>``."""
    return get_configured_model_aliases()


def model_alias_config_source(name: str) -> ModelAliasConfigSource | None:
    """Return where *name* is configured, or ``None`` when it is implicit.

    When the builtin and custom maps both define the name, the custom map is the
    effective source because it wins during merge.
    """
    alias = name.strip()
    if not alias:
        return None
    if alias in get_custom_model_aliases():
        return "custom"
    if alias in get_builtin_model_aliases():
        return "builtin"
    return None


def default_model_alias_name() -> str:
    """Return the implicit "default" model alias name."""
    return DEFAULT_MODEL_ALIAS_NAME


def coder_model_alias_for_provider(provider: str) -> str:
    """Return the ``<provider>_coder`` model alias name for *provider*."""
    return f"{provider.strip()}{PROVIDER_CODER_ALIAS_SUFFIX}"


def role_model_directive_value(role: str) -> str:
    """Return the ``%model`` directive value (``@<role>``) for a role alias."""
    return f"@{role}"


def registered_provider_names_for_aliases() -> list[str]:
    """Return registered LLM provider names, or ``[]`` on discovery failure."""
    try:
        from .registry import registered_provider_names

        return registered_provider_names()
    except Exception:
        return []


def is_provider_coder_alias(name: str) -> bool:
    """Return ``True`` if *name* is a ``<provider>_coder`` alias for a provider."""
    from . import config

    if not name.endswith(PROVIDER_CODER_ALIAS_SUFFIX):
        return False
    provider = name[: -len(PROVIDER_CODER_ALIAS_SUFFIX)]
    return bool(provider) and provider in config._registered_provider_names()


def role_model_alias_names() -> set[str]:
    """Return the fixed implicit role aliases (``default`` plus role aliases)."""
    return {
        DEFAULT_MODEL_ALIAS_NAME,
        *ROLE_ALIAS_FALLBACKS,
        *IMPLICIT_ALIAS_TARGETS,
    }


def provider_coder_model_alias_names() -> set[str]:
    """Return a ``<provider>_coder`` alias for every registered provider."""
    from . import config

    return {
        coder_model_alias_for_provider(provider)
        for provider in config._registered_provider_names()
    }


def special_model_alias_names() -> set[str]:
    """Return every implicit (non-user-configured) model alias name."""
    return role_model_alias_names() | provider_coder_model_alias_names()


def model_alias_names() -> set[str]:
    """Return every name that is a user-facing model alias."""
    return set(get_model_aliases()) | special_model_alias_names()


def model_alias_kind(name: str) -> str:
    """Classify *name* for display as a default, role, provider coder, or user."""
    if name == DEFAULT_MODEL_ALIAS_NAME:
        return "default"
    if name in ROLE_ALIAS_FALLBACKS or name in IMPLICIT_ALIAS_TARGETS:
        return "role"
    if is_provider_coder_alias(name):
        return "provider_coder"
    return "user"


def model_alias_description(name: str) -> str | None:
    """Return the display description for a model alias, if one is known."""
    alias = name.strip()
    if not alias:
        return None
    if alias in ROLE_ALIAS_DESCRIPTIONS:
        return ROLE_ALIAS_DESCRIPTIONS[alias]
    if is_provider_coder_alias(alias):
        provider = alias[: -len(PROVIDER_CODER_ALIAS_SUFFIX)]
        return f"Coder follow-up agents for plans authored by {provider}."
    return _custom_model_alias_descriptions().get(alias)


def strip_model_alias_prefix(value: str) -> str:
    """Strip the surface ``@`` marker from a model alias token, if present."""
    if value.startswith("@"):
        return value[1:]
    return value


def implicit_model_alias_fallback(name: str) -> str | None:
    """Return the immediate implicit fallback alias for *name*, if any."""
    fallback = implicit_model_alias_fallback_reference(name)
    if fallback is None:
        return None
    reference, _ = split_model_effort(fallback)
    return strip_model_alias_prefix(reference)


def implicit_model_alias_fallback_reference(name: str) -> str | None:
    """Return the raw immediate implicit fallback reference for *name*."""
    alias = name.strip()
    fallback = ROLE_ALIAS_FALLBACKS.get(alias)
    if fallback is None and is_provider_coder_alias(alias):
        fallback = f"@{CODER_MODEL_ALIAS_NAME}"
    return fallback


def implicit_model_alias_fallback_effort(name: str) -> str | None:
    """Return the effort overlay on *name*'s implicit fallback, if any."""
    fallback = implicit_model_alias_fallback_reference(name)
    if fallback is None:
        return None
    _, effort = split_model_effort(fallback)
    return effort


def implicit_model_alias_value(name: str) -> str | None:
    """Return a concrete/selector implicit target value for *name*, if any."""
    return IMPLICIT_ALIAS_TARGETS.get(name.strip())


def format_model_directive_value(value: str) -> str:
    """Return *value* formatted for a user-facing ``%model`` directive."""
    bare_value = strip_model_alias_prefix(value)
    if bare_value in model_alias_names():
        return f"@{bare_value}"
    return value


def _clean_string_mapping(value: Any) -> dict[str, str]:
    """Return stripped string-to-string entries from a config mapping."""
    if not isinstance(value, dict):
        return {}

    cleaned: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            continue
        alias = key.strip()
        target = item.strip()
        if alias and target:
            cleaned[alias] = target
    return cleaned
