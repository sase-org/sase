"""Configuration reader for the LLM provider layer."""

from typing import Any

from sase.config import load_merged_config

_ALIAS_RESOLUTION_DEPTH_LIMIT = 16


def get_llm_provider_config() -> dict[str, Any]:
    """Read the ``llm_provider`` section from ``sase.yml``.

    Looks for ``~/.config/sase/sase.yml`` and returns the ``llm_provider``
    section, or an empty dict if not found.

    Returns:
        The llm_provider configuration dict.
    """
    try:
        data = load_merged_config()

        if not isinstance(data, dict):
            return {}

        config = data.get("llm_provider", {}) or {}
        if not isinstance(config, dict):
            return {}
        return config
    except Exception:
        return {}


def get_model_aliases() -> dict[str, str]:
    """Return cleaned ``llm_provider.model_aliases`` entries from config."""
    aliases = get_llm_provider_config().get("model_aliases", {})
    if not isinstance(aliases, dict):
        return {}

    cleaned: dict[str, str] = {}
    for key, value in aliases.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        alias = key.strip()
        target = value.strip()
        if alias and target:
            cleaned[alias] = target
    return cleaned


def resolve_model_alias(model: str) -> str:
    """Resolve a configured model alias to its final configured target.

    Unknown aliases return *model* unchanged.  Cycles and overly deep chains
    also fall back to the original input so a bad config cannot crash launches.
    """
    aliases = get_model_aliases()
    if not aliases:
        return model

    original = model
    current = model.strip()
    if current not in aliases:
        return model
    seen: set[str] = set()
    for _ in range(_ALIAS_RESOLUTION_DEPTH_LIMIT):
        if current not in aliases:
            return current
        if current in seen:
            return original
        seen.add(current)
        current = aliases[current].strip()
        if not current:
            return original
    return original
